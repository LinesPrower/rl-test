"""Custom Torch model with ship-to-entity attention."""

from __future__ import annotations

import torch
import gymnasium as gym
from torch import nn
from ray.rllib.models.modelv2 import restore_original_dimensions
from ray.rllib.models.torch.torch_modelv2 import TorchModelV2
from ray.rllib.utils.annotations import override


def count_trainable_parameters(module: nn.Module) -> int:
    return sum(p.numel() for p in module.parameters() if p.requires_grad)


class AttentionBlock(nn.Module):
    def __init__(self, d_model: int, num_heads: int, ff_scale: int):
        super().__init__()
        self.attn = nn.MultiheadAttention(embed_dim=d_model, num_heads=num_heads, batch_first=True)
        self.norm1 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, ff_scale * d_model),
            nn.ReLU(),
            nn.Linear(ff_scale * d_model, d_model),
        )
        self.norm2 = nn.LayerNorm(d_model)

    def forward(self, q: torch.Tensor, kv: torch.Tensor, key_padding_mask: torch.Tensor) -> torch.Tensor:
        attn_out, _ = self.attn(q, kv, kv, key_padding_mask=key_padding_mask)
        h = self.norm1(q + attn_out)
        ff_out = self.ff(h)
        return self.norm2(h + ff_out)


class SpaceMinersAttentionModel(TorchModelV2, nn.Module):
    def __init__(self, obs_space, action_space, num_outputs, model_config, name, **kwargs):
        TorchModelV2.__init__(self, obs_space, action_space, num_outputs, model_config, name)
        nn.Module.__init__(self)

        custom_cfg = dict(model_config.get("custom_model_config", {}))
        custom_cfg.update(kwargs)

        model_obs_space = getattr(obs_space, "original_space", obs_space)
        if isinstance(model_obs_space, gym.spaces.Dict):
            model_subspaces = model_obs_space.spaces
        elif isinstance(model_obs_space, dict):
            model_subspaces = model_obs_space
        else:
            raise TypeError(
                "SpaceMinersAttentionModel expects a Dict observation space "
                f"(or flattened Box with original_space), got {type(model_obs_space)!r}"
            )

        d_model = int(custom_cfg.get("d_model", 128))
        num_heads = int(custom_cfg.get("num_heads", 4))
        attention_layers = int(custom_cfg.get("attention_layers", 2))
        ff_scale = int(custom_cfg.get("attention_ff_scale", 2))
        trunk_hidden = int(custom_cfg.get("trunk_hidden", 512))

        self.global_encoder = nn.Sequential(
            nn.Linear(model_subspaces["global"].shape[0], d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
            nn.ReLU(),
        )
        self.ship_encoder = nn.Sequential(
            nn.Linear(model_subspaces["my_ships"].shape[-1], d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
            nn.ReLU(),
        )
        self.asteroid_encoder = nn.Sequential(
            nn.Linear(model_subspaces["asteroids"].shape[-1], d_model),
            nn.ReLU(),
            nn.Linear(d_model, d_model),
            nn.ReLU(),
        )
        self.attention_stack = nn.ModuleList(
            [AttentionBlock(d_model=d_model, num_heads=num_heads, ff_scale=ff_scale) for _ in range(attention_layers)]
        )

        # 3 own ships * d_model + one global vector.
        trunk_input = d_model * 4
        self.trunk = nn.Sequential(
            nn.Linear(trunk_input, trunk_hidden),
            nn.ReLU(),
            nn.Linear(trunk_hidden, trunk_hidden),
            nn.ReLU(),
        )
        self.policy_head = nn.Linear(trunk_hidden, num_outputs)
        self.value_head = nn.Sequential(
            nn.Linear(trunk_hidden, trunk_hidden // 2),
            nn.ReLU(),
            nn.Linear(trunk_hidden // 2, 1),
        )
        self._value_out = None

    @override(TorchModelV2)
    def forward(self, input_dict, state, seq_lens):
        obs = input_dict["obs"]
        if not isinstance(obs, dict):
            obs = restore_original_dimensions(obs, self.obs_space, tensorlib="torch")
        global_obs = obs["global"].float()
        my_ships = obs["my_ships"].float()
        opp_ships = obs["opp_ships"].float()
        asteroids = obs["asteroids"].float()
        asteroid_mask = obs["asteroid_mask"].float()

        batch_size = global_obs.shape[0]

        global_emb = self.global_encoder(global_obs)
        my_emb = self.ship_encoder(my_ships)
        opp_emb = self.ship_encoder(opp_ships)
        ast_emb = self.asteroid_encoder(asteroids)

        kv = torch.cat([my_emb, opp_emb, ast_emb], dim=1)
        fixed_mask = torch.ones((batch_size, my_emb.shape[1] + opp_emb.shape[1]), device=global_obs.device)
        valid_mask = torch.cat([fixed_mask, asteroid_mask], dim=1)
        key_padding_mask = valid_mask < 0.5

        q = my_emb
        for block in self.attention_stack:
            q = block(q=q, kv=kv, key_padding_mask=key_padding_mask)

        trunk_in = torch.cat([q.reshape(batch_size, -1), global_emb], dim=1)
        trunk_out = self.trunk(trunk_in)

        logits = self.policy_head(trunk_out)
        self._value_out = self.value_head(trunk_out).squeeze(-1)
        return logits, state

    @override(TorchModelV2)
    def value_function(self):
        assert self._value_out is not None, "value_function called before forward"
        return self._value_out
