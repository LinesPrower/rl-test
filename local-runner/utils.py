"""
Utility functions for the game runner.
"""

def round_floats(obj, decimals=6):
    """
    Recursively round all float values in a nested data structure to a specified number of decimals.
    
    This is useful for reducing JSON payload sizes and file sizes for replays
    while maintaining sufficient precision for visualization and calculations.
    
    Args:
        obj: The object to process (dict, list, tuple, float, or other)
        decimals: Number of decimal places to round to (default: 6)
    
    Returns:
        The same structure with all floats rounded to the specified precision
        
    Examples:
        >>> round_floats(3.141592653589793, 6)
        3.141593
        >>> round_floats({'x': 1.123456789, 'y': 2.987654321}, 6)
        {'x': 1.123457, 'y': 2.987654}
        >>> round_floats([1.111111111, 2.222222222], 6)
        [1.111111, 2.222222]
    """
    if isinstance(obj, float):
        return round(obj, decimals)
    elif isinstance(obj, dict):
        return {key: round_floats(value, decimals) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [round_floats(item, decimals) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(round_floats(item, decimals) for item in obj)
    else:
        return obj
