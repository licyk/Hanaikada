/** Display labels for the normalised sampler and scheduler names (ComfyUI's vocabulary). */

const SAMPLERS: Record<string, string> = {
  euler: 'Euler',
  euler_ancestral: 'Euler a',
  euler_cfg_pp: 'Euler CFG++',
  euler_ancestral_cfg_pp: 'Euler a CFG++',
  heun: 'Heun',
  heunpp2: 'Heun++ 2',
  dpm_2: 'DPM2',
  dpm_2_ancestral: 'DPM2 a',
  lms: 'LMS',
  dpm_fast: 'DPM fast',
  dpm_adaptive: 'DPM adaptive',
  dpmpp_2s_ancestral: 'DPM++ 2S a',
  dpmpp_sde: 'DPM++ SDE',
  dpmpp_2m: 'DPM++ 2M',
  dpmpp_2m_sde: 'DPM++ 2M SDE',
  dpmpp_3m_sde: 'DPM++ 3M SDE',
  ddpm: 'DDPM',
  lcm: 'LCM',
  ipndm: 'iPNDM',
  deis: 'DEIS',
  res_multistep: 'Res Multistep',
  er_sde: 'ER SDE',
  ddim: 'DDIM',
  uni_pc: 'UniPC',
  uni_pc_bh2: 'UniPC BH2',
  plms: 'PLMS',
  tcd: 'TCD',
  restart: 'Restart',
};

/** A friendly label for a normalised sampler name; unknown names are shown as they are. */
export function samplerLabel(norm: string | null | undefined): string {
  if (!norm) return '';
  return SAMPLERS[norm] ?? norm;
}
