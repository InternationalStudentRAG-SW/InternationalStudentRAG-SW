import type { VercelRequest, VercelResponse } from '@vercel/node'

export const config = { maxDuration: 180 }

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Admin-Secret',
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  Object.entries(CORS_HEADERS).forEach(([k, v]) => res.setHeader(k, v))

  if (req.method === 'OPTIONS') {
    return res.status(204).end()
  }

  const BACKEND_URL = process.env.BACKEND_URL
  if (!BACKEND_URL) {
    return res.status(500).json({ error: 'BACKEND_URL is not configured' })
  }

  const url = new URL(req.url ?? '/', `https://${req.headers['host'] ?? 'localhost'}`)
  const backendPath = url.pathname.replace(/^\/api/, '') || '/'
  const targetUrl = `${BACKEND_URL}${backendPath}${url.search}`

  const forwardHeaders: Record<string, string> = {}
  const auth = req.headers['authorization']
  if (auth) forwardHeaders['Authorization'] = String(auth)
  const ct = req.headers['content-type']
  if (ct) forwardHeaders['Content-Type'] = String(ct)

  try {
    let body: BodyInit | undefined
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      if (String(ct ?? '').includes('multipart/form-data')) {
        // 파일 업로드: raw body 그대로 전달
        body = req.body
      } else {
        body = JSON.stringify(req.body ?? {})
      }
    }

    const backendRes = await fetch(targetUrl, {
      method: req.method,
      headers: forwardHeaders,
      body,
    })

    const contentType = backendRes.headers.get('content-type') ?? ''
    res.status(backendRes.status)

    if (contentType.includes('text/event-stream')) {
      res.setHeader('Content-Type', 'text/event-stream')
      res.setHeader('Cache-Control', 'no-cache')
      res.setHeader('X-Accel-Buffering', 'no')

      const reader = backendRes.body!.getReader()
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        res.write(decoder.decode(value, { stream: true }))
      }
      return res.end()
    }

    const data = await backendRes.text()
    res.setHeader('Content-Type', contentType || 'application/json')
    return res.send(data)
  } catch (e) {
    return res.status(500).json({ error: String(e) })
  }
}
