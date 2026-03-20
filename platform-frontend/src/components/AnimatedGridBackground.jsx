import { useEffect, useRef } from 'react'

export default function AnimatedGridBackground({ theme = 'light' }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const context = canvas.getContext('2d')
    if (!context) return

    let animationFrameId
    let tick = 0

    const resize = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
    }

    const draw = () => {
      context.clearRect(0, 0, canvas.width, canvas.height)
      const cols = Math.ceil(canvas.width / 80)
      const rows = Math.ceil(canvas.height / 80)

      const isLight = theme === 'light'
      const lineColor = isLight ? '0, 0, 0' : '255, 255, 255'
      const lineBase = isLight ? 0.07 : 0.03
      const lineDelta = isLight ? 0.02 : 0.01

      for (let col = 0; col <= cols; col += 1) {
        const x = col * 80
        const wave = Math.sin(tick * 0.01 + col * 0.3) * 2
        context.beginPath()
        context.moveTo(x + wave, 0)
        context.lineTo(x - wave, canvas.height)
        context.strokeStyle = `rgba(${lineColor}, ${lineBase + Math.sin(tick * 0.005 + col) * lineDelta})`
        context.lineWidth = 0.5
        context.stroke()
      }

      for (let row = 0; row <= rows; row += 1) {
        const y = row * 80
        const wave = Math.sin(tick * 0.008 + row * 0.4) * 2
        context.beginPath()
        context.moveTo(0, y + wave)
        context.lineTo(canvas.width, y - wave)
        context.strokeStyle = `rgba(${lineColor}, ${lineBase + Math.cos(tick * 0.006 + row) * lineDelta})`
        context.lineWidth = 0.5
        context.stroke()
      }

      for (let col = 0; col <= cols; col += 1) {
        for (let row = 0; row <= rows; row += 1) {
          const brightness = Math.sin(tick * 0.02 + col * 0.5 + row * 0.7) * 0.5 + 0.5
          if (brightness > 0.7) {
            context.beginPath()
            context.arc(col * 80, row * 80, 1.5, 0, Math.PI * 2)
            context.fillStyle = `rgba(242, 106, 46, ${brightness * 0.3})`
            context.fill()
          }
        }
      }

      tick += 1
      animationFrameId = window.requestAnimationFrame(draw)
    }

    resize()
    window.addEventListener('resize', resize)
    draw()

    return () => {
      window.cancelAnimationFrame(animationFrameId)
      window.removeEventListener('resize', resize)
    }
  }, [theme])

  return <canvas ref={canvasRef} className="pointer-events-none fixed inset-0 z-0" />
}
