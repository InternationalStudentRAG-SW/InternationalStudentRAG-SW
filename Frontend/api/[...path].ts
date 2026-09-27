export const config = { runtime: 'edge' }

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Admin-Secret',
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
  })
}

export default async function handler(request: Request): Promise<Response> {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS })
  }

  const url = new URL(request.url)
  // Strip /api prefix added by VITE_API_BASE_URL=/api
  const backendPath = url.pathname.replace(/^\/api/, '') || '/'
  const method = request.method

  const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY
  const RUNPOD_ENDPOINT_ID = process.env.RUNPOD_ENDPOINT_ID
  if (!RUNPOD_API_KEY || !RUNPOD_ENDPOINT_ID) {
    return json({ error: 'RunPod configuration missing' }, 500)
  }

  const forwardHeaders: Record<string, string> = {}
  const auth = request.headers.get('Authorization')
  if (auth) forwardHeaders['Authorization'] = auth
  const adminSecret = request.headers.get('X-Admin-Secret')
  if (adminSecret) forwardHeaders['X-Admin-Secret'] = adminSecret

  let body: unknown = null
  if (method !== 'GET' && method !== 'HEAD') {
    const ct = request.headers.get('content-type') ?? ''
    if (ct.includes('multipart/form-data')) {
      return json({ error: 'File upload is not supported through the Vercel proxy. Use the RunPod endpoint directly.' }, 501)
    }
    try {
      body = await request.json()
    } catch {
      // empty or non-JSON body
    }
  }

  try {
    const runpodRes = await fetch(
      `https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/runsync`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${RUNPOD_API_KEY}`,
        },
        body: JSON.stringify({
          input: { path: backendPath, method, body, headers: forwardHeaders },
        }),
      }
    )

    if (!runpodRes.ok) {
      const text = await runpodRes.text()
      return json({ error: `RunPod error ${runpodRes.status}: ${text}` }, 502)
    }

    const result = await runpodRes.json()
    const output = result.output

    if (!output) {
      return json({ error: 'RunPod returned no output', raw: result }, 502)
    }

    const statusCode: number = output.status_code ?? 200
    const responseBody = output.body

    // /chat/stream returns SSE text — re-emit as event-stream
    if (backendPath === '/chat/stream') {
      return new Response(typeof responseBody === 'string' ? responseBody : '', {
        status: statusCode,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          ...CORS_HEADERS,
        },
      })
    }

    const bodyStr =
      typeof responseBody === 'string' ? responseBody : JSON.stringify(responseBody ?? {})

    return new Response(bodyStr, {
      status: statusCode,
      headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
    })
  } catch (e) {
    return json({ error: String(e) }, 500)
  }
}
