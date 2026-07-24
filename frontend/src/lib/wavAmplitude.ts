export interface WavAmplitudeEnvelope {
  samplesPerSecond: number
  values: number[]
}

function fourCC(view: DataView, offset: number): string {
  return String.fromCharCode(
    view.getUint8(offset),
    view.getUint8(offset + 1),
    view.getUint8(offset + 2),
    view.getUint8(offset + 3)
  )
}

/**
 * Build a small RMS envelope from the PCM WAV returned by the cloned-voice
 * service. Playback remains on the normal HTMLAudioElement path; this only
 * reads the already-downloaded bytes so portrait motion can follow the sound
 * that is actually being heard.
 */
export async function readWavAmplitude(
  blob: Blob,
  samplesPerSecond = 24
): Promise<WavAmplitudeEnvelope | null> {
  try {
    const buffer = await blob.arrayBuffer()
    const view = new DataView(buffer)
    if (
      view.byteLength < 44 ||
      fourCC(view, 0) !== "RIFF" ||
      fourCC(view, 8) !== "WAVE"
    ) {
      return null
    }

    let offset = 12
    let audioFormat = 0
    let channels = 0
    let sampleRate = 0
    let blockAlign = 0
    let bitsPerSample = 0
    let dataOffset = 0
    let dataSize = 0

    while (offset + 8 <= view.byteLength) {
      const id = fourCC(view, offset)
      const size = view.getUint32(offset + 4, true)
      const body = offset + 8
      if (body + size > view.byteLength) break

      if (id === "fmt " && size >= 16) {
        audioFormat = view.getUint16(body, true)
        channels = view.getUint16(body + 2, true)
        sampleRate = view.getUint32(body + 4, true)
        blockAlign = view.getUint16(body + 12, true)
        bitsPerSample = view.getUint16(body + 14, true)
      } else if (id === "data") {
        dataOffset = body
        dataSize = size
      }

      offset = body + size + (size % 2)
    }

    if (
      audioFormat !== 1 ||
      bitsPerSample !== 16 ||
      channels < 1 ||
      sampleRate < 1 ||
      blockAlign < channels * 2 ||
      dataSize < blockAlign
    ) {
      return null
    }

    const frameCount = Math.floor(dataSize / blockAlign)
    const framesPerBucket = Math.max(1, Math.floor(sampleRate / samplesPerSecond))
    const values: number[] = []
    let maxRms = 0

    for (let frameStart = 0; frameStart < frameCount; frameStart += framesPerBucket) {
      const frameEnd = Math.min(frameCount, frameStart + framesPerBucket)
      let sumSquares = 0
      let sampleCount = 0

      for (let frame = frameStart; frame < frameEnd; frame += 1) {
        const base = dataOffset + frame * blockAlign
        for (let channel = 0; channel < channels; channel += 1) {
          const sample = view.getInt16(base + channel * 2, true) / 32768
          sumSquares += sample * sample
          sampleCount += 1
        }
      }

      const rms = sampleCount ? Math.sqrt(sumSquares / sampleCount) : 0
      values.push(rms)
      maxRms = Math.max(maxRms, rms)
    }

    if (maxRms <= 0) {
      return { samplesPerSecond, values }
    }

    return {
      samplesPerSecond,
      values: values.map((value) => Math.min(1, value / maxRms)),
    }
  } catch {
    return null
  }
}
