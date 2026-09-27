"""One vocabulary for samplers and schedulers across platforms, for search.

Every platform keeps its own spelling in ``sampler``/``scheduler``; ``sampler_norm`` maps the
WebUI's display names, InvokeAI's diffusers names and NovelAI's ``k_`` names onto ComfyUI's
(``Euler a`` → ``euler_ancestral``). Unknown names pass through lower-cased with spaces as ``_``.
"""

import re

# WebUI display name (lower-cased) → ComfyUI sampler name.
_WEBUI_SAMPLERS = {
    "euler a": "euler_ancestral",
    "euler": "euler",
    "euler cfg++": "euler_cfg_pp",
    "euler a cfg++": "euler_ancestral_cfg_pp",
    "lms": "lms",
    "heun": "heun",
    "heun pp2": "heunpp2",
    "dpm2": "dpm_2",
    "dpm2 a": "dpm_2_ancestral",
    "dpm++ 2s a": "dpmpp_2s_ancestral",
    "dpm++ 2s a cfg++": "dpmpp_2s_ancestral_cfg_pp",
    "dpm++ 2m": "dpmpp_2m",
    "dpm++ 2m cfg++": "dpmpp_2m_cfg_pp",
    "dpm++ sde": "dpmpp_sde",
    "dpm++ 2m sde": "dpmpp_2m_sde",
    "dpm++ 2m sde gpu": "dpmpp_2m_sde_gpu",
    "dpm++ 2m sde heun": "dpmpp_2m_sde_heun",
    "dpm++ 3m sde": "dpmpp_3m_sde",
    "dpm fast": "dpm_fast",
    "dpm adaptive": "dpm_adaptive",
    "lcm": "lcm",
    "ddim": "ddim",
    "ddim cfg++": "ddim_cfg_pp",
    "ddpm": "ddpm",
    "plms": "plms",
    "unipc": "uni_pc",
    "restart": "restart",
    "deis": "deis",
    "ipndm": "ipndm",
    "ipndm_v": "ipndm_v",
    "tcd": "tcd",
    "res multistep": "res_multistep",
    "er sde": "er_sde",
    "seeds 2": "seeds_2",
    "seeds 3": "seeds_3",
    "sa-solver": "sa_solver",
    "gradient estimation": "gradient_estimation",
    "undefined": "euler",
}

# InvokeAI scheduler names, without the ``_k`` (Karras) suffix → ComfyUI sampler name.
_INVOKEAI_SAMPLERS = {
    "euler": "euler",
    "euler_a": "euler_ancestral",
    "deis": "deis",
    "ddim": "ddim",
    "ddpm": "ddpm",
    "dpmpp_2s": "dpmpp_2s",
    "dpmpp_2m": "dpmpp_2m",
    "dpmpp_3m": "dpmpp_3m",
    "dpmpp_2m_sde": "dpmpp_2m_sde",
    "dpmpp_sde": "dpmpp_sde",
    "er_sde": "er_sde",
    "heun": "heun",
    "kdpm_2": "dpm_2",
    "kdpm_2_a": "dpm_2_ancestral",
    "lms": "lms",
    "pndm": "pndm",
    "unipc": "uni_pc",
    "lcm": "lcm",
    "tcd": "tcd",
}

# NovelAI (and the WebUI's samplers_map) ``k_`` names.
_K_SAMPLERS = {
    "k_euler_ancestral": "euler_ancestral",
    "k_euler": "euler",
    "k_lms": "lms",
    "k_heun": "heun",
    "k_dpm_2": "dpm_2",
    "k_dpm_2_ancestral": "dpm_2_ancestral",
    "k_dpmpp_2s_ancestral": "dpmpp_2s_ancestral",
    "k_dpmpp_2m": "dpmpp_2m",
    "k_dpmpp_2m_sde": "dpmpp_2m_sde",
    "k_dpmpp_sde": "dpmpp_sde",
    "k_dpm_fast": "dpm_fast",
    "k_dpm_adaptive": "dpm_adaptive",
    "ddim": "ddim",
    "ddim_v3": "ddim",
    "plms": "plms",
}

# WebUI schedule-type display names (lower-cased) → ComfyUI scheduler names.
_SCHEDULERS = {
    "automatic": "automatic",
    "karras": "karras",
    "exponential": "exponential",
    "polyexponential": "polyexponential",
    "normal": "normal",
    "simple": "simple",
    "uniform": "uniform",
    "sgm uniform": "sgm_uniform",
    "linear quadratic": "linear_quadratic",
    "kl optimal": "kl_optimal",
    "ddim": "ddim_uniform",
    "align your steps": "align_your_steps",
    "align your steps gits": "align_your_steps_gits",
    "align your steps 11": "align_your_steps_11",
    "align your steps 32": "align_your_steps_32",
    "beta": "beta",
    "turbo": "turbo",
    "native": "normal",
}

# Suffixes older WebUI versions folded into the sampler name: "DPM++ 2M Karras".
_OLD_SUFFIXES = ("Karras", "Exponential", "Polyexponential", "SGM Uniform", "Uniform")


def _slug(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower()).replace("++", "pp").replace("+", "p")


def split_webui_sampler(sampler: str) -> tuple[str, str | None]:
    """``"DPM++ 2M Karras"`` → ``("DPM++ 2M", "Karras")`` when the name is not a sampler on its own."""
    if sampler.lower() in _WEBUI_SAMPLERS:
        return sampler, None
    for suffix in _OLD_SUFFIXES:
        if sampler.endswith(" " + suffix):
            return sampler[: -len(suffix) - 1], suffix
    return sampler, None


def normalize_sampler(name: str | None) -> str | None:
    """Map a sampler name from any platform onto ComfyUI's vocabulary."""
    if not name or not name.strip():
        return None
    lower = name.strip().lower()
    for table in (_WEBUI_SAMPLERS, _K_SAMPLERS, _INVOKEAI_SAMPLERS):
        if lower in table:
            return table[lower]
    return _slug(name)


def normalize_scheduler(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    lower = name.strip().lower()
    return _SCHEDULERS.get(lower, _slug(name))


def split_invokeai_scheduler(name: str) -> tuple[str, str | None]:
    """InvokeAI keeps sampler and schedule in one field: ``dpmpp_2m_k`` is DPM++ 2M with Karras sigmas."""
    if name.endswith("_k") and name[:-2] in _INVOKEAI_SAMPLERS:
        return name[:-2], "karras"
    return name, None
