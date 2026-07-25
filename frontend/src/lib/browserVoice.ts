export interface BrowserVoiceCandidate {
  name: string;
  lang: string;
  localService: boolean;
  default?: boolean;
}

const MALE_VOICE_NAMES =
  /\b(male|alex|andrew|arthur|brian|christopher|daniel|david|davis|eric|fred|george|gordon|guy|jacob|james|joey|liam|mark|matthew|michael|oliver|ralph|roger|ryan|stefan|steffan|thomas|tom|tony|william)\b/i;

const FEMALE_VOICE_NAMES =
  /\b(female|aria|hazel|heera|jenny|karen|moira|samantha|susan|tessa|veena|victoria|zira)\b/i;

export function isLikelyMaleVoice(voice: BrowserVoiceCandidate): boolean {
  return MALE_VOICE_NAMES.test(voice.name);
}

function scoreVoice(voice: BrowserVoiceCandidate): number {
  const name = voice.name.toLowerCase();
  const language = voice.lang.toLowerCase();
  let score = language === "en-us" ? 40 : language === "en-gb" ? 35 : 20;

  if (name.includes("google uk english male")) score += 500;
  if (isLikelyMaleVoice(voice)) score += 350;
  if (FEMALE_VOICE_NAMES.test(voice.name)) score -= 500;
  if (name.includes("natural")) score += 100;
  if (name.includes("online")) score += 35;
  if (name.includes("microsoft")) score += 25;
  if (name.includes("google")) score += 20;
  if (voice.localService) score += 10;

  return score;
}

/**
 * Chrome exposes voice names and languages but no gender metadata. Prefer a
 * known English male voice and fall back to the best English voice only when
 * the operating system has no identifiable male voice installed.
 */
export function selectPreferredBrowserVoice<T extends BrowserVoiceCandidate>(
  voices: readonly T[],
): T | null {
  const english = voices.filter((voice) =>
    voice.lang.toLowerCase().startsWith("en"),
  );
  const candidates = english.length ? english : [...voices];
  const maleCandidates = candidates.filter(isLikelyMaleVoice);
  const pool = maleCandidates.length ? maleCandidates : candidates;

  return [...pool].sort(
    (left, right) => scoreVoice(right) - scoreVoice(left),
  )[0] ?? null;
}
