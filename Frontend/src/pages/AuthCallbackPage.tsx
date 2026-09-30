import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import { getMe } from '../services/api'

export default function AuthCallbackPage() {
  const navigate = useNavigate()

  useEffect(() => {
    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === 'SIGNED_IN' && session) {
        localStorage.setItem('token', session.access_token)
        navigate('/', { replace: true })
        try {
          const user = await getMe()
          localStorage.setItem('role', user.role)
          if (!user.nationality) navigate('/additional-info', { replace: true })
        } catch {
          navigate('/additional-info', { replace: true })
        }
      }
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  return null
}
