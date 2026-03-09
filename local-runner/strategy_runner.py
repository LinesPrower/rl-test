import struct
import socket
import select
import json
import subprocess
import time
import logging
import platform
import threading
import queue
import sys
from typing import List, Dict, Optional, Union
import psutil

MEMORY_LIMIT_MB = 256
TURN_TIMEOUT_SECONDS = 0.05

# Docker support is optional
try:
    from docker_manager import DockerManager
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

# Check if we're on Windows
IS_WINDOWS = platform.system() == 'Windows'

def _read_from_pipe_with_timeout(pipe, timeout):
    """Cross-platform function to read from a pipe with timeout."""
    if IS_WINDOWS:
        # On Windows, use threading to read from pipe
        result_queue = queue.Queue()
        
        def reader():
            try:
                data = pipe.read()
                result_queue.put(('data', data))
            except Exception as e:
                result_queue.put(('error', e))
        
        thread = threading.Thread(target=reader)
        thread.daemon = True
        thread.start()
        
        try:
            result_type, result = result_queue.get(timeout=timeout)
            if result_type == 'error':
                raise result
            return result
        except queue.Empty:
            return None
    else:
        # On Unix systems, use select
        fd = pipe.fileno()
        rlist, _, _ = select.select([fd], [], [], timeout)
        if rlist:
            return pipe.read()
        return None

def _check_pipe_ready(pipe, timeout):
    """Cross-platform function to check if data is ready on a pipe."""
    if IS_WINDOWS:
        # On Windows, try to peek at the pipe using a short timeout read
        result_queue = queue.Queue()
        
        def checker():
            try:
                # Try to read a line with a very short blocking operation
                line = pipe.readline()
                result_queue.put(('ready', line is not None and line != ''))
            except:
                result_queue.put(('ready', False))
        
        thread = threading.Thread(target=checker)
        thread.daemon = True
        thread.start()
        
        try:
            result_type, is_ready = result_queue.get(timeout=timeout)
            return is_ready
        except queue.Empty:
            return False
    else:
        # On Unix systems, use select
        fd = pipe.fileno()
        rlist, _, _ = select.select([fd], [], [], timeout)
        return len(rlist) > 0

class StrategyRunner:
    def __init__(self, docker_manager: Optional['DockerManager'] = None, logger: logging.Logger = None, enforce_timeouts: bool = True):
        if docker_manager is not None and not DOCKER_AVAILABLE:
            raise ImportError("Docker support is not available.")
        self.docker_manager = docker_manager
        self.logger = logger or logging.getLogger(__name__)
        self.strategy_processes = []
        self.strategy_stderr = []
        self.enforce_timeouts = enforce_timeouts
        self.logger.info("StrategyRunner initialized with throttling fix via replace_file_content")

    def initialize_strategies(self, game_state, strategies: List[Dict], logger: logging.Logger = None):
        self.logger = logger or self.logger
        self.strategy_processes = []
        self.strategy_processes = []
        self.strategy_stderr = []
        self.last_memory_check = [0] * len(strategies)
        for i, strategy in enumerate(strategies):
            if strategy is None:
                self.strategy_processes.append(None)
                continue

            if 'file' in strategy:  # Local strategy file
                process = self.start_local_strategy(strategy)
            else:  # Docker container strategy
                self.logger.info(f"Strategy {i}: starting Docker container...")
                t0 = time.time()
                process = self.start_docker_strategy(strategy)
                self.logger.info(f"Strategy {i}: container+exec ready in {time.time()-t0:.3f}s")

            self.strategy_processes.append(process)
            self.strategy_stderr.append([])

            # Send initial game info to the strategy
            info = game_state.get_initial_info()
            info.update({
                'player_index': i
            })
            initial_info = json.dumps(info)
            self.logger.info(f"Strategy {i}: sending initial config ({len(initial_info)} bytes)")
            self.send_to_strategy(process, initial_info)
            self.logger.info(f"Strategy {i}: initial config sent, waiting for READY...")

            # Wait for READY signal from the strategy
            ready_timeout = 3 if self.enforce_timeouts else None
            if not self._wait_for_ready(process, timeout=ready_timeout):
                self.logger.error(f"Strategy {i} failed READY check")
                if not self.enforce_timeouts:  # Local runner mode
                    self.logger.error(f"Strategy {i} did not print 'READY' within 3 seconds of startup")
                    self.logger.error(f"Make sure your strategy reads initial game info and prints 'READY' (then flushes stdout)")
                
                # Capture stderr before cleaning up the strategy
                stderr_output = ""
                if not isinstance(process, dict):
                    # Local process - try to read stderr
                    if process.stderr:
                        try:
                            # Use cross-platform function to check if there's stderr data available
                            stderr_output = _read_from_pipe_with_timeout(process.stderr, 0.1)
                            if stderr_output is None:
                                stderr_output = ""
                        except Exception as e:
                            self.logger.warning(f"Could not read stderr for strategy {i}: {e}")
                    
                    try:
                        parent = psutil.Process(process.pid)
                        children = parent.children(recursive=True)
                        for child in children:
                            try:
                                child.terminate()
                            except psutil.NoSuchProcess:
                                pass
                        parent.terminate()
                        gone, alive = psutil.wait_procs(children + [parent], timeout=5)
                        for p in alive:
                            p.kill()
                    except psutil.NoSuchProcess:
                        pass
                else:
                    # Docker container - get logs from the EXEC socket, not the container log
                    try:
                        self.logger.info(f"Attempting to read stderr from failed exec socket for strategy {i}")
                        # Log exec inspect to get exit code
                        if 'exec_id' in process:
                            inspect = self.docker_manager.inspect_exec(process['exec_id'])
                            if inspect:
                                self.logger.info(f"Strategy {i} exec inspect: Running={inspect.get('Running')}, ExitCode={inspect.get('ExitCode')}, Pid={inspect.get('Pid')}")
                        # First check if we accumulated stderr during _wait_for_ready
                        if 'accumulated_stderr' in process and process['accumulated_stderr']:
                            stderr_output = process['accumulated_stderr']
                            self.logger.info(f"Using accumulated stderr from _wait_for_ready: {repr(stderr_output)}")
                        else:
                            # Try to read any remaining data from the socket
                            stdout, stderr = self._read_from_socket(process["socket"], timeout=0.5)
                            stderr_output = stderr
                            self.logger.info(f"Strategy {i} post-failure socket read: stdout={repr(stdout[:200] if stdout else '')}, stderr={repr(stderr[:200] if stderr else '')}")
                            if stdout: # Also log any stdout just in case
                                stderr_output += "\n--STDOUT--\n" + stdout
                    except Exception as e:
                        # If reading from the socket fails, fall back to container logs as a last resort
                        self.logger.warning(f"Could not read from exec socket for strategy {i}: {e}. Falling back to container.logs().")
                        try:
                            stderr_output = process['container'].logs(stderr=True, stdout=True).decode('utf-8')
                        except Exception as e_log:
                            self.logger.warning(f"Could not get Docker container logs for strategy {i}: {e_log}")
                            stderr_output = "[Could not retrieve any logs]"
                    
                    self.docker_manager.cleanup_container(process['container'], process['strategy'])
                
                # Store the stderr output
                self.logger.error(f"Strategy {i} stderr during READY check: {stderr_output}")
                if stderr_output:
                    self.strategy_stderr[i].append(stderr_output)
                    self.logger.error(f"Strategy {i} stderr during READY check: {stderr_output}")
                
                self.strategy_processes[i] = None  # Mark as cleaned up to prevent double cleanup
                game_state.players[i].is_active = False
                game_state.players[i].disqualification_reason = "Ready check timeout"
            else:
                self.logger.info(f"Strategy {i} initialized successfully and is ready")

    def _handle_strategy_failure(self, process, i, from_timeout: bool = False):
        """Inspects why a strategy failed and returns (reason, inspect_data)."""
        reason = "Strategy crashed or exited unexpectedly"
        inspect_data = None
        
        if DOCKER_AVAILABLE and isinstance(process, dict) and 'exec_id' in process:
            # Docker strategy - check exit code
            inspect_data = self.docker_manager.inspect_exec(process['exec_id'])
            if inspect_data:
                exit_code = inspect_data.get('ExitCode')
                is_running = inspect_data.get('Running')
                self.logger.info(f"Strategy {i} exited with code {exit_code}")
                if from_timeout:
                    # Timeout-driven classification must not map ExitCode=None to runtime error.
                    if is_running or exit_code is None:
                        reason = "Time limit exceeded"
                    elif exit_code == 137:
                        reason = "Memory limit exceeded (OOM Killed)"
                    elif exit_code == 0:
                        reason = "Strategy exited unexpectedly (Exit Code 0)"
                    else:
                        reason = f"Runtime Error (Exit Code {exit_code})"
                else:
                    if exit_code == 137:
                        reason = "Memory limit exceeded (OOM Killed)"
                    elif exit_code is not None and exit_code != 0:
                        reason = f"Runtime Error (Exit Code {exit_code})"
            elif from_timeout:
                reason = "Time limit exceeded"
        elif from_timeout:
            # Primary event is timeout and we have no better runtime signal.
            reason = "Time limit exceeded"

        return reason, inspect_data

    def get_actions(self, game_state):
        actions = []
        turn_number = getattr(game_state, 'tick', None)
        for i, process in enumerate(self.strategy_processes):
            if not process or not game_state.players[i].is_active:
                actions.append(None)
                continue

            turn_started_at = time.perf_counter()
            try:
                # Send turn info
                turn_info = game_state.get_input(i)
                self.send_to_strategy(process, turn_info)

                # Receive action with conditional timeout
                # NOTE: Memory limits are no longer polled. We rely on Docker native limits (OOM Kill 137).
                # If a container exceeds memory, the socket read below will fail/return empty, catching the crash.


                # Receive action with conditional timeout
                if self.enforce_timeouts:
                    timeout = TURN_TIMEOUT_SECONDS
                    action, stderr, raw_output = self.receive_from_strategy(process, timeout=timeout)
                    if stderr:
                        self.strategy_stderr[i].append(stderr)  # Store stderr

                    if action is None:
                        if raw_output:
                            # JSON parsing failed - we have the raw output
                            raise json.JSONDecodeError(f"Invalid JSON from strategy", raw_output, 0)
                        else:
                            raise TimeoutError("Strategy timed out")
                else:
                    # No timeout enforcement for local runner
                    action, stderr, raw_output = self.receive_from_strategy(process, timeout=None)
                    if stderr:
                        self.strategy_stderr[i].append(stderr)  # Store stderr

                    if action is None and raw_output:
                        # JSON parsing failed - we have the raw output for better error reporting
                        raise json.JSONDecodeError(f"Invalid JSON from strategy", raw_output, 0)
                    elif action is None:
                        raise TimeoutError("Strategy returned no output")

                # Validate action
                if not self._validate_action(action):
                    raise ValueError("Invalid action format")

                actions.append(action)
            except TimeoutError:
                if self.enforce_timeouts:
                    # Try to capture any stderr output for debugging
                    stderr_output = ""
                    if not isinstance(process, dict):
                        # Local process
                        if process.stderr:
                            # Use cross-platform function to check if there's stderr data available
                            try:
                                stderr_output = _read_from_pipe_with_timeout(process.stderr, 0.01)
                                if stderr_output is None:
                                    stderr_output = ""
                            except Exception as ex:
                                self.logger.warning(f"Could not read stderr for strategy {i}: {ex}")
                    else:
                        # Docker container - try to get recent logs
                        try:
                            # Get the last few lines of stderr logs
                            stderr_output = process['container'].logs(stderr=True, stdout=False, tail=50).decode('utf-8')
                        except Exception as ex:
                            self.logger.warning(f"Could not get Docker stderr for strategy {i}: {ex}")
                            
                    if stderr_output:
                        self.logger.error(f"Strategy {i} stderr before failure: {stderr_output}")
                        # Also store it in the strategy_stderr for final results
                        self.strategy_stderr[i].append(stderr_output)

                    failure_reason, inspect_data = self._handle_strategy_failure(process, i, from_timeout=True)
                    running = inspect_data.get('Running') if inspect_data else None
                    exit_code = inspect_data.get('ExitCode') if inspect_data else None
                    self.logger.error(
                        "Strategy %s timeout diagnostics: timeout_seconds=%s running=%s "
                        "exit_code=%s has_stderr=%s stderr_len=%s",
                        i,
                        TURN_TIMEOUT_SECONDS,
                        running,
                        exit_code,
                        bool(stderr_output),
                        len(stderr_output),
                    )
                    self.logger.error(f"Strategy {i} error: {failure_reason}")

                    game_state.players[i].is_active = False
                    game_state.players[i].disqualification_reason = failure_reason
                    actions.append(None)
                else:
                    # This shouldn't happen when timeouts are disabled, but just in case
                    # When timeouts are disabled, this usually means the strategy died/crashed
                    # Strategy died/crashed or timed out (if no timeout)
                    failure_reason, _ = self._handle_strategy_failure(process, i, from_timeout=False)
                    self.logger.warning(f"Strategy {i} failed: {failure_reason}")
                    
                    # Try to capture stderr for debugging
                    stderr_output = ""
                    if not isinstance(process, dict) and process and process.stderr:
                        try:
                            stderr_output = _read_from_pipe_with_timeout(process.stderr, 0.1)
                            if stderr_output is None:
                                stderr_output = ""
                        except Exception as ex:
                            self.logger.warning(f"Could not read stderr for strategy {i}: {ex}")
                    
                    if stderr_output:
                        self.logger.error(f"Strategy {i} stderr before crash: {stderr_output}")
                        self.strategy_stderr[i].append(stderr_output)
                    
                    game_state.players[i].is_active = False
                    game_state.players[i].disqualification_reason = failure_reason
                    actions.append(None)
            except ValueError as e:
                self.logger.error(f"Strategy {i} returned invalid action: {e}")
                game_state.players[i].is_active = False
                game_state.players[i].disqualification_reason = str(e)
                actions.append(None)
            except json.JSONDecodeError as e:
                # Enhanced error reporting for JSON parsing issues
                if not self.enforce_timeouts:  # Local runner mode - provide detailed feedback
                    self.logger.error(f"Strategy {i} returned invalid JSON: {e}")
                    self.logger.error(f"Strategy {i} raw output that caused JSON error: {repr(e.doc)}")
                    self.logger.error(f"Expected format example: {{\"commands\": [{{\"ship_id\": 0, \"acceleration\": {{\"x\": 0.5, \"y\": -0.3}}, \"push\": false}}]}}")
                    if len(e.doc) == 0:
                        self.logger.error(f"Strategy {i} sent empty output - make sure your strategy prints a JSON response and flushes stdout")
                    elif not e.doc.strip():
                        self.logger.error(f"Strategy {i} sent only whitespace - check for extra newlines or spaces")
                    else:
                        self.logger.error(f"Strategy {i} output length: {len(e.doc)} characters")
                else:
                    self.logger.error(f"Strategy {i} returned invalid JSON: {e}")
                
                game_state.players[i].is_active = False
                game_state.players[i].disqualification_reason = f"Invalid JSON: {str(e)}"
                actions.append(None)
            except Exception as e:
                self.logger.error(f"Unexpected error from strategy {i}: {e}")
                
                # Try to capture stderr for debugging
                if not isinstance(process, dict) and process and process.stderr:
                    try:
                        stderr_output = _read_from_pipe_with_timeout(process.stderr, 0.1)
                        if stderr_output:
                            self.logger.error(f"Strategy {i} stderr during unexpected error: {stderr_output}")
                            self.strategy_stderr[i].append(stderr_output)
                    except Exception as stderr_ex:
                        self.logger.warning(f"Could not read stderr for strategy {i} after unexpected error: {stderr_ex}")
                
                game_state.players[i].is_active = False
                game_state.players[i].disqualification_reason = f"Unexpected error: {str(e)}"
                actions.append(None)
            finally:
                elapsed_ms = (time.perf_counter() - turn_started_at) * 1000
                self.logger.info(
                    "Timing: turn=%s strategy=%s elapsed_ms=%.3f",
                    turn_number if turn_number is not None else "unknown",
                    i,
                    elapsed_ms,
                )

        return actions

    def _validate_action(self, action):
        if not isinstance(action, dict):
            self.logger.error(f"Action must be a dictionary/object, got {type(action).__name__}: {repr(action)}")
            return False

        if 'commands' not in action:
            self.logger.error(f"Action must have a 'commands' field. Got keys: {list(action.keys())}")
            self.logger.error(f"Expected: {{\"commands\": [...]}}")
            return False

        if not isinstance(action['commands'], list):
            self.logger.error(f"'commands' must be a list/array, got {type(action['commands']).__name__}")
            return False

        if len(action['commands']) == 0:
            self.logger.error(f"'commands' list is empty - you need at least one command for your ships")
            return False

        # Check each command
        for i, command in enumerate(action['commands']):
            if not isinstance(command, dict):
                self.logger.error(f"Command {i} must be a dictionary/object, got {type(command).__name__}: {repr(command)}")
                return False

            # Check required keys
            required_keys = ['ship_id', 'acceleration', 'push']
            missing_keys = [key for key in required_keys if key not in command]
            if missing_keys:
                self.logger.error(f"Command {i} missing required keys: {missing_keys}")
                self.logger.error(f"Command {i} has keys: {list(command.keys())}")
                self.logger.error(f"Required keys: {required_keys}")
                return False

            # Validate ship_id
            try:
                ship_id = int(command['ship_id'])
            except (ValueError, TypeError):
                self.logger.error(f"Command {i} 'ship_id' must be an integer, got {type(command['ship_id']).__name__}: {repr(command['ship_id'])}")
                return False

            # Validate acceleration structure
            if not isinstance(command['acceleration'], dict):
                self.logger.error(f"Command {i} 'acceleration' must be a dictionary/object, got {type(command['acceleration']).__name__}: {repr(command['acceleration'])}")
                return False

            acc_required_keys = ['x', 'y']
            acc_missing_keys = [key for key in acc_required_keys if key not in command['acceleration']]
            if acc_missing_keys:
                self.logger.error(f"Command {i} 'acceleration' missing keys: {acc_missing_keys}")
                self.logger.error(f"Command {i} 'acceleration' has keys: {list(command['acceleration'].keys())}")
                return False

            # Validate acceleration components
            try:
                x = float(command['acceleration']['x'])
                y = float(command['acceleration']['y'])
            except (ValueError, TypeError) as e:
                self.logger.error(f"Command {i} acceleration components must be numbers")
                self.logger.error(f"Got x: {type(command['acceleration']['x']).__name__} = {repr(command['acceleration']['x'])}")
                self.logger.error(f"Got y: {type(command['acceleration']['y']).__name__} = {repr(command['acceleration']['y'])}")
                return False

            # Validate push
            if not isinstance(command['push'], bool):
                self.logger.error(f"Command {i} 'push' must be a boolean (true/false), got {type(command['push']).__name__}: {repr(command['push'])}")
                return False

        return True

    def cleanup_strategies(self):
        for i, process in enumerate(self.strategy_processes):
            if process is None:
                continue
            if not isinstance(process, dict):
                # Kill the entire process tree (shell + strategy child).
                # With shell=True, process.terminate() only kills the shell,
                # leaving the strategy orphaned on Linux/Windows.
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    parent.terminate()
                    gone, alive = psutil.wait_procs(children + [parent], timeout=5)
                    for p in alive:
                        p.kill()
                except psutil.NoSuchProcess:
                    pass  # Process already exited
            else:  # Docker container
                self.docker_manager.cleanup_container(process['container'], process['strategy'])
                self.logger.info(f"Strategy {i} stderr:\n{''.join(self.strategy_stderr[i])}")

    def start_local_strategy(self, strategy: Dict):
        # Use shell=True to interpret the run_command as a shell command
        # This allows commands with quotes and shell features to work correctly
        self.logger.info(f"Starting strategy with command: {strategy['run_command']}")
        process = subprocess.Popen(
            strategy['run_command'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # for local runs, stderr is printed to console
            stderr=sys.stderr,
            text=True,
            bufsize=1,
            shell=True
        )
        return process

    def start_docker_strategy(self, strategy: Dict):
        if not DOCKER_AVAILABLE or self.docker_manager is None:
            raise ImportError("Docker support is not available. Please install required dependencies.")
        container, socket, exec_id = self.docker_manager.run_strategy(strategy)
        return {'container': container, 'socket': socket, 'strategy': strategy, 'exec_id': exec_id}

    def send_to_strategy(self, process, data: str):
        if not isinstance(process, dict):
            process.stdin.write(f"{data}\n")
            process.stdin.flush()
        else:  # Docker container
            process['socket']._sock.sendall(data.encode('utf-8') + b'\n')

    def receive_from_strategy(self, process, timeout=0.05):
        if not isinstance(process, dict):
            if timeout is None:
                # No timeout - wait indefinitely
                line = process.stdout.readline()
                if not line:
                    return None, None, None
                try:
                    parsed_action = json.loads(line)
                    return parsed_action, None, line.strip()
                except json.JSONDecodeError:
                    # Return the raw line for better error reporting
                    return None, None, line.strip()
            # Use timeout with cross-platform approach
            if IS_WINDOWS:
                # On Windows, use threading to read with timeout
                result_queue = queue.Queue()
                
                def reader():
                    try:
                        line = process.stdout.readline()
                        result_queue.put(('data', line))
                    except Exception as e:
                        result_queue.put(('error', e))
                
                thread = threading.Thread(target=reader)
                thread.daemon = True
                thread.start()
                
                try:
                    result_type, line = result_queue.get(timeout=timeout)
                    if result_type == 'error':
                        return None, None, None
                    if not line:
                        return None, None, None
                    try:
                        parsed_action = json.loads(line)
                        return parsed_action, None, line.strip()
                    except json.JSONDecodeError:
                        return None, None, line.strip()
                except queue.Empty:
                    return None, "", None
            else:
                # Unix systems - use select
                fd = process.stdout.fileno()
                rlist, _, _ = select.select([fd], [], [], timeout)
                if rlist:
                    line = process.stdout.readline()
                    if not line:
                        return None, None, None
                    try:
                        parsed_action = json.loads(line)
                        return parsed_action, None, line.strip()
                    except json.JSONDecodeError:
                        return None, None, line.strip()
                else:
                    return None, "", None
        else:  # Docker container
            if timeout is None:
                # For Docker containers, we can't easily wait indefinitely, so use a very large timeout
                timeout = 3600  # 1 hour
            stdout, stderr = self._read_from_socket(process["socket"], timeout)
            if not self.enforce_timeouts:  # Only log in local runner mode for debugging
                self.logger.info(f"stdout: '{stdout}' stderr: '{stderr}'")
            if not stdout:
                return None, stderr, None
            try:
                parsed_action = json.loads(stdout)
                return parsed_action, stderr, stdout.strip()
            except json.JSONDecodeError:
                # Return the raw stdout for better error reporting
                return None, stderr, stdout.strip()

    def _read_from_socket(self, sock, timeout):
        def recv_with_timeout(sock, size, timeout):
            ready = select.select([sock], [], [], timeout)
            if not ready[0]:
                raise socket.timeout("Socket operation timed out")
            return sock.recv(size)

        stdout, stderr = b"", b""
        try:
            while True:
                header = recv_with_timeout(sock._sock, 8, timeout)
                if len(header) < 8:
                    break

                stream_type = header[0]
                length = struct.unpack(">I", header[4:])[0]

                if length == 0:
                    continue

                content = recv_with_timeout(sock._sock, length, timeout)
                if stream_type == 1:
                    stdout += content
                    # If we got stdout and it looks like a complete JSON response, return immediately
                    # to avoid waiting the full timeout. Only continue waiting if we need stderr for debugging.
                    stdout_str = stdout.decode('utf-8')
                    if stdout_str.strip() and (stdout_str.strip().endswith('}') or stdout_str.strip().endswith(']')):
                        # Try a quick stderr check with minimal timeout, then return
                        try:
                            stderr_header = recv_with_timeout(sock._sock, 8, 0.001)  # 1ms timeout for stderr
                            if len(stderr_header) == 8:
                                stderr_stream_type = stderr_header[0]
                                stderr_length = struct.unpack(">I", stderr_header[4:])[0]
                                if stderr_stream_type == 2 and stderr_length > 0:
                                    stderr_content = recv_with_timeout(sock._sock, stderr_length, 0.001)
                                    stderr += stderr_content
                        except socket.timeout:
                            pass  # No stderr available, that's fine
                        return stdout_str, stderr.decode('utf-8')
                elif stream_type == 2:
                    stderr += content

            return stdout.decode('utf-8'), stderr.decode('utf-8')
        except socket.timeout:
            # Return whatever we've collected so far, even on timeout
            return stdout.decode('utf-8'), stderr.decode('utf-8')

    def _wait_for_ready(self, process, timeout=3):
        start = time.time()
        buffer = ""
        accumulated_stderr = ""
        while timeout is None or time.time() - start < timeout:
            remaining = timeout - (time.time() - start) if timeout is not None else 86400
            if not isinstance(process, dict):
                # Cross-platform approach for reading from stdout
                if IS_WINDOWS:
                    # On Windows, use threading to read with timeout
                    result_queue = queue.Queue()
                    
                    def reader():
                        try:
                            line = process.stdout.readline()
                            result_queue.put(('data', line))
                        except Exception as e:
                            result_queue.put(('error', e))
                    
                    thread = threading.Thread(target=reader)
                    thread.daemon = True
                    thread.start()
                    
                    try:
                        result_type, line = result_queue.get(timeout=remaining)
                        if result_type == 'error' or not line:
                            continue
                        if line.strip() == "READY":
                            return True
                    except queue.Empty:
                        continue
                else:
                    # Unix systems - use select
                    fd = process.stdout.fileno()
                    rlist, _, _ = select.select([fd], [], [], remaining)
                    if rlist:
                        line = process.stdout.readline()
                        if not line:
                            continue
                        if line.strip() == "READY":
                            return True
            else:
                try:
                    # Use a short timeout to check for data frequently
                    # This avoids waiting for the full timeout duration if the "READY" signal comes in early
                    # but isn't a JSON object (which _read_from_socket optimizes for)
                    poll_kwargs = {'timeout': min(remaining, 0.1)}
                    stdout, stderr = self._read_from_socket(process["socket"], **poll_kwargs)
                    # Accumulate stderr for potential error reporting
                    if stderr:
                        accumulated_stderr += stderr
                        self.logger.info(f"[READY-wait] stderr chunk: {repr(stderr[:500])}")
                    if stdout:
                        self.logger.info(f"[READY-wait] stdout chunk: {repr(stdout[:500])}")
                except TimeoutError:
                    continue
                buffer += stdout
                for line in buffer.splitlines():
                    if line.strip() == "READY":
                        return True
                buffer = ""
        
        # Store accumulated stderr in the process for later retrieval
        if isinstance(process, dict) and accumulated_stderr:
            process['accumulated_stderr'] = accumulated_stderr
        
        return False
