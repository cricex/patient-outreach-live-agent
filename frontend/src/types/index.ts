export interface PromptSet {
  id: string
  name: string
  description: string
  system_prompt: string
  call_brief: string
  voice: string | null
  model: string | null
  target_phone_number: string | null
  created_at: string
  updated_at: string
}

export interface StartCallRequest {
  target_phone_number?: string | null
  system_prompt?: string | null
  call_brief?: string | null
  simulate?: boolean
}

export interface StartCallResponse {
  call_id: string
  to: string
  prompt_used: string
}

export interface CallStatus {
  uptime_sec: number
  call: {
    current: any | null
    last: any | null
  }
  voicelive: any
  media: any
}

export interface DiagnosticEvent {
  type: string
  timestamp: number
  data: Record<string, any>
}
