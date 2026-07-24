"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * The Andrew particle portrait — the twin's primary brand asset and visible
 * embodiment. It reconstructs a matted photograph as a network of nodes and
 * links that assemble from a coherent field, settle into a recognisable face,
 * and then breathe. It recurs across the landing hero, the app identity, and
 * voice mode.
 *
 * SUBJECT SELECTION IS A MATTE, NOT A BRIGHTNESS CUTOFF
 * The source asset (andrew-portrait.png) carries a real subject alpha matte
 * built with U^2-Net: transparent background, solid face/hair/neck/torso, and
 * feathered hair/shoulder edges. Two responsibilities are kept separate:
 *   1. ALPHA decides whether a pixel belongs to Andrew. The photographic
 *      background is never sampled, and dark facial features (hair, eyes, suit)
 *      are NOT mistaken for background the way a global luminance cutoff did.
 *   2. LUMINANCE only shapes each particle — radius, tone, opacity — and always
 *      leaves a minimum presence so dark regions stay intentionally rendered
 *      rather than deleted.
 *
 * BLENDING (no rectangular field)
 * The canvas is transparent. Each particle's opacity is multiplied by the
 * matte alpha (so the silhouette feathers into the page at its true edge) and
 * by a lower-body dissolution (shoulders/hands fade downward into the page).
 * There is no rectangular or circular mask — the shape you see is the subject.
 *
 * MODES: "hero" (full assembly + links + signals + breathing), "identity"
 * (compact quick settle), "voice" (settled + audio-reactive mouth region),
 * "static" (one settled render; also the reduced-motion result).
 *
 * PERFORMANCE: Canvas 2D, one reused point array, DPR capped at 2, density
 * scales with box size, rAF stops once settled unless the mode needs motion,
 * and all work pauses off-screen or when the tab is hidden.
 */
export type PortraitMode = "hero" | "identity" | "voice" | "static"

export interface AndrewPortraitProps
  extends React.HTMLAttributes<HTMLDivElement> {
  src: string
  mode?: PortraitMode
  /** Pixels between samples. Smaller is denser and more expensive. */
  gap?: number
  maxRadius?: number
  /** Voice mode: current output amplitude 0..1, drives mouth-region reaction. */
  amplitude?: number
}

type Point = {
  tx: number
  ty: number
  sx: number
  sy: number
  r: number
  delay: number
  phase: number
  mouth: boolean
  mouthSide: number
  ma: number // matte alpha 0..1 (silhouette feather)
  by: number // lower-body dissolution 0..1
  lum: number
}

const REC709 = { r: 0.2126, g: 0.7152, b: 0.0722 }
const ALPHA_IN = 0.36 // matte threshold for inclusion
const MIN_RADIUS = 0.5 // dark features still get a small dot

function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)
const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

export function AndrewPortrait({
  src,
  mode = "hero",
  gap = 4,
  maxRadius = 2.5,
  amplitude = 0,
  className,
  ...props
}: AndrewPortraitProps) {
  const hostRef = React.useRef<HTMLDivElement | null>(null)
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null)
  const [status, setStatus] = React.useState<"loading" | "ready" | "error">(
    "loading"
  )
  const ampRef = React.useRef(amplitude)
  React.useEffect(() => {
    ampRef.current = amplitude
  }, [amplitude])

  React.useEffect(() => {
    const host = hostRef.current
    const canvas = canvasRef.current
    if (!host || !canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
    const animate = mode !== "static" && !reduceMotion
    const continuous = animate && (mode === "hero" || mode === "voice")

    let points: Point[] = []
    let cols = 0
    let frame = 0
    let cancelled = false
    let onScreen = true
    let startTime = 0
    const assembleMs = mode === "identity" ? 900 : 1600

    function build(image: HTMLImageElement, width: number, height: number) {
      const scale = Math.min(width / image.width, height / image.height)
      const drawW = Math.round(image.width * scale)
      const drawH = Math.round(image.height * scale)
      const offsetX = Math.round((width - drawW) / 2)
      const offsetY = Math.round((height - drawH) / 2)

      const off = document.createElement("canvas")
      off.width = drawW
      off.height = drawH
      const offCtx = off.getContext("2d", { willReadFrequently: true })
      if (!offCtx) return
      offCtx.drawImage(image, 0, 0, drawW, drawH)

      let data: Uint8ClampedArray
      try {
        data = offCtx.getImageData(0, 0, drawW, drawH).data
      } catch {
        setStatus("error")
        return
      }

      // Pass 1: subject vertical bounds (for lower-body dissolution) from the
      // MATTE, so the fade is anchored to the visible subject, not the frame.
      let subjTop = drawH
      let subjBot = 0
      for (let py = 0; py < drawH; py += 2) {
        for (let px = 0; px < drawW; px += 2) {
          if (data[(py * drawW + px) * 4 + 3] / 255 >= ALPHA_IN) {
            if (py < subjTop) subjTop = py
            if (py > subjBot) subjBot = py
            break
          }
        }
      }
      const subjH = Math.max(1, subjBot - subjTop)

      const rnd = mulberry32(0x1a5eeded)
      const next: Point[] = []
      cols = Math.floor(drawW / gap)
      const cx = width / 2
      const cy = height / 2
      const diag = Math.hypot(width, height)

      for (let gy = 0; gy * gap < drawH; gy++) {
        for (let gx = 0; gx < cols; gx++) {
          const px = gx * gap
          const py = gy * gap
          const i = (py * drawW + px) * 4
          const alpha = data[i + 3] / 255

          // INCLUSION = matte. Background is never sampled.
          if (alpha < ALPHA_IN) {
            next.push(EMPTY)
            continue
          }

          const lum =
            (REC709.r * data[i] +
              REC709.g * data[i + 1] +
              REC709.b * data[i + 2]) /
            255

          // Thin only the large near-black interior a little, so the dark suit
          // reads as a field of fine dots rather than a heavy blob — but never
          // enough to erase the silhouette or dark facial features.
          if (lum < 0.09 && rnd() < 0.32) {
            next.push(EMPTY)
            continue
          }

          const jx = (rnd() - 0.5) * gap * 0.55
          const jy = (rnd() - 0.5) * gap * 0.55
          const tx = offsetX + px + jx
          const ty = offsetY + py + jy

          // Matte feather → silhouette edge softness.
          const ma = clamp01((alpha - 0.2) / 0.6)

          // Lower-body dissolution: full above 0.6 of subject height, dropping
          // to a faint residue at the bottom so shoulders/hands melt into page.
          const fy = clamp01((py - subjTop) / subjH)
          const by = fy < 0.6 ? 1 : 0.12 + 0.88 * (1 - (fy - 0.6) / 0.4)

          // Seeded off-screen start; a field gathering material, not confetti.
          const ang = rnd() * Math.PI * 2
          const dist = diag * (0.55 + rnd() * 0.5)
          const sx = cx + Math.cos(ang) * dist
          const sy = cy + Math.sin(ang) * dist

          // Landmarks first: nearer the centre settles earliest.
          const rel = Math.hypot(tx - cx, ty - cy) / (diag / 2)
          const delay = clamp01(rel) * 0.5 + rnd() * 0.12

          // The source portrait's mouth is left of the image centre because
          // Andrew is turned slightly. An ellipse tied to image coordinates
          // keeps speech motion on the lips instead of moving half the face.
          const mouthX = (px / drawW - 0.465) / 0.105
          const mouthY = (py / drawH - 0.425) / 0.052
          const mouth = mouthX * mouthX + mouthY * mouthY <= 1
          const mouthSide = clamp01((mouthY + 1) / 2) * 2 - 1

          // Luminance shapes the particle; a floor keeps dark features present.
          const r = MIN_RADIUS + lum * (maxRadius - MIN_RADIUS)

          next.push({
            tx,
            ty,
            sx,
            sy,
            r,
            delay,
            phase: (gx + gy) * 0.35 + rnd(),
            mouth,
            mouthSide,
            ma,
            by: clamp01(by),
            lum,
          })
        }
      }
      points = next
    }

    // Per-point position with per-point assembly delay + breathing/voice drift.
    function posX(p: Point, settleAll: number, t: number): number {
      const local = animate
        ? easeOutCubic(clamp01((settleAll - p.delay) / (1 - p.delay + 0.001)))
        : 1
      let x = p.sx + (p.tx - p.sx) * local
      if (settleAll >= 1 && continuous) {
        x += Math.sin(t + p.phase) * 0.9
        if (mode === "voice" && p.mouth)
          x += Math.sin(t * 13 + p.phase) * ampRef.current * 0.8
      }
      return x
    }
    function posY(p: Point, settleAll: number, t: number): number {
      const local = animate
        ? easeOutCubic(clamp01((settleAll - p.delay) / (1 - p.delay + 0.001)))
        : 1
      let y = p.sy + (p.ty - p.sy) * local
      if (settleAll >= 1 && continuous) {
        y += Math.cos(t + p.phase) * 0.9
        if (mode === "voice" && p.mouth) {
          const jawDirection = p.mouthSide >= 0 ? 1 : -1
          y +=
            jawDirection * ampRef.current * 2.4 +
            Math.cos(t * 13 + p.phase) * ampRef.current * 0.7
        }
      }
      return y
    }

    function paint(now: number) {
      const { width, height } = canvas!.getBoundingClientRect()
      ctx!.clearRect(0, 0, width, height)
      if (!points.length) return
      if (!startTime) startTime = now
      const elapsed = now - startTime
      const settleAll = animate ? clamp01(elapsed / assembleMs) : 1
      const settled = settleAll >= 1
      const t = now / 1000

      // ── Links (only once mostly settled), opacity from matte + body fade ──
      const linkAlpha = clamp01((settleAll - 0.72) / 0.28)
      if (linkAlpha > 0.01 && mode !== "identity") {
        const rows = Math.ceil(points.length / cols)
        ctx!.lineWidth = 0.5
        ctx!.beginPath()
        for (let row = 0; row < rows; row++) {
          for (let col = 0; col < cols; col++) {
            const a = points[row * cols + col]
            if (!a || a.r === 0) continue
            const ax = posX(a, settleAll, t)
            const ay = posY(a, settleAll, t)
            const right = col + 1 < cols ? points[row * cols + col + 1] : null
            const down = row + 1 < rows ? points[(row + 1) * cols + col] : null
            for (const b of [right, down]) {
              if (!b || b.r === 0) continue
              ctx!.moveTo(ax, ay)
              ctx!.lineTo(posX(b, settleAll, t), posY(b, settleAll, t))
            }
          }
        }
        ctx!.strokeStyle = `rgba(150,150,150,${0.06 * linkAlpha})`
        ctx!.stroke()
      }

      // ── Sparse orange signals travelling through lit facial nodes ──
      if (settled && (mode === "hero" || mode === "voice")) {
        const brand = brandRGB()
        const amp = ampRef.current
        const count = 5
        for (let s = 0; s < count; s++) {
          const speed = mode === "voice" ? 0.4 + amp : 0.3
          const prog = (t * speed + s / count) % 1
          const idx = Math.floor(prog * points.length)
          const p = points[idx]
          if (!p || p.r === 0 || p.lum < 0.35 || p.by < 0.5) continue
          ctx!.beginPath()
          ctx!.arc(posX(p, 1, t), posY(p, 1, t), 1.5, 0, Math.PI * 2)
          ctx!.fillStyle = `rgba(${brand},0.85)`
          ctx!.fill()
        }
      }

      // ── Dots: warm-white, tone by luminance, floor keeps dark features ──
      const dotBrand = mode === "voice" && ampRef.current > 0.04
        ? brandRGB()
        : ""
      for (const p of points) {
        if (p.r === 0) continue
        const local = animate
          ? easeOutCubic(clamp01((settleAll - p.delay) / (1 - p.delay + 0.001)))
          : 1
        const x = posX(p, settleAll, t)
        const y = posY(p, settleAll, t)
        const tone = Math.max(0.34, 0.32 + p.lum * 0.62)
        const a = tone * p.ma * p.by * local
        if (a <= 0.01) continue
        const speakingMouth =
          mode === "voice" && p.mouth && ampRef.current > 0.04
        const radius = speakingMouth
          ? p.r * (1 + ampRef.current * 0.45)
          : p.r
        ctx!.beginPath()
        ctx!.arc(x, y, radius, 0, Math.PI * 2)
        ctx!.fillStyle = speakingMouth
          ? `rgba(${dotBrand},${Math.min(1, a + ampRef.current * 0.3)})`
          : `rgba(236,234,230,${a})`
        ctx!.fill()
      }
    }

    function loop(now: number) {
      if (cancelled) return
      paint(now)
      const settled = !startTime ? false : now - startTime >= assembleMs
      if (onScreen && (continuous || !settled)) {
        frame = requestAnimationFrame(loop)
      } else {
        frame = 0
      }
    }

    function kick() {
      if (frame || cancelled || !onScreen) return
      frame = requestAnimationFrame(loop)
    }

    function resize(image: HTMLImageElement) {
      const rect = host!.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas!.width = Math.round(rect.width * dpr)
      canvas!.height = Math.round(rect.height * dpr)
      canvas!.style.width = `${rect.width}px`
      canvas!.style.height = `${rect.height}px`
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)
      build(image, rect.width, rect.height)
      startTime = 0
    }

    const image = new Image()
    image.crossOrigin = "anonymous"
    image.onload = () => {
      if (cancelled) return
      setStatus("ready")
      resize(image)
      if (animate) kick()
      else paint(performance.now())
    }
    image.onerror = () => {
      if (!cancelled) setStatus("error")
    }
    image.src = src

    const io = new IntersectionObserver(
      (entries) => {
        onScreen = entries[0]?.isIntersecting ?? true
        if (onScreen) kick()
      },
      { threshold: 0.01 }
    )
    io.observe(host)

    const onVis = () => {
      if (document.hidden) {
        cancelAnimationFrame(frame)
        frame = 0
      } else {
        kick()
      }
    }
    document.addEventListener("visibilitychange", onVis)

    const ro = new ResizeObserver(() => {
      if (image.complete && image.naturalWidth > 0) {
        resize(image)
        if (animate) kick()
        else paint(performance.now())
      }
    })
    ro.observe(host)

    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
      io.disconnect()
      ro.disconnect()
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [src, mode, gap, maxRadius])

  return (
    <div ref={hostRef} className={cn("relative", className)} {...props}>
      {/* Extremely restrained atmospheric illumination behind the head, using
          the brand token — helps the figure feel lit from within the page
          rather than pasted on. Never reveals a rectangle. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(58% 44% at 52% 34%, color-mix(in srgb, var(--brand) 8%, transparent), transparent 70%)",
        }}
      />
      <canvas
        ref={canvasRef}
        className={cn(
          "relative h-full w-full transition-opacity duration-700",
          status === "ready" ? "opacity-100" : "opacity-0"
        )}
      />
      {status === "error" && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center">
          <div
            aria-hidden
            className="size-24 rounded-full border border-[var(--border)]"
            style={{
              background:
                "radial-gradient(circle at 50% 40%, var(--brand-soft), transparent 70%)",
            }}
          />
        </div>
      )}
    </div>
  )
}

const EMPTY: Point = {
  tx: -1, ty: -1, sx: -1, sy: -1, r: 0, delay: 0, phase: 0,
  mouth: false, mouthSide: 0, ma: 0, by: 0, lum: 0,
}

/** Read the resolved --brand as "r,g,b" for canvas fill. */
function brandRGB(): string {
  if (typeof window === "undefined") return "255,122,26"
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue("--brand")
    .trim()
  const c = hexToRgb(v)
  return c ? `${c.r},${c.g},${c.b}` : "255,122,26"
}

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  return m
    ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) }
    : null
}
