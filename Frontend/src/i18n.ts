export const UI_LABELS = {
  ko: {
    sidebarTitle: '유학생 생활·행정\n안내 챗봇',
    sidebarDesc: '학교 문서를 바탕으로 필요한 정보를 빠르게 찾을 수 있는 스마트 챗봇',
    sidebarStatus: '상담 가능',
    faqTitle: '자주 묻는 질문',
    chatEmpty: '질문을 입력하여 대화를 시작하세요.',
    chatPlaceholder: '예: 기숙사 신청 기간은 언제인가요?',
    btnClear: '초기화',
    btnSend: '전송',
    chatSubtitle: '문서 기반 안내 · 빠른 응답',
  },
  en: {
    sidebarTitle: 'International Student\nLife Guide',
    sidebarDesc: 'A smart chatbot to quickly find the information you need based on university documents.',
    sidebarStatus: 'Available',
    faqTitle: 'Frequently Asked Questions',
    chatEmpty: 'Enter a question to start the conversation.',
    chatPlaceholder: 'e.g. When is the dormitory application period?',
    btnClear: 'Clear',
    btnSend: 'Send',
    chatSubtitle: 'Document-based · Fast Response',
  },
  zh: {
    sidebarTitle: '留学生生活·行政\n指南聊天机器人',
    sidebarDesc: '基于学校文件，快速找到所需信息的智能聊天机器人。',
    sidebarStatus: '可咨询',
    faqTitle: '常见问题',
    chatEmpty: '请输入问题开始对话。',
    chatPlaceholder: '例：宿舍申请时间是什么时候？',
    btnClear: '清除',
    btnSend: '发送',
    chatSubtitle: '基于文档 · 快速响应',
  },
  es: {
    sidebarTitle: 'Guía de Vida para\nEstudiantes Internacionales',
    sidebarDesc: 'Un chatbot inteligente para encontrar rápidamente la información que necesitas.',
    sidebarStatus: 'Disponible',
    faqTitle: 'Preguntas Frecuentes',
    chatEmpty: 'Ingresa una pregunta para iniciar la conversación.',
    chatPlaceholder: 'Ej: ¿Cuándo es el período de solicitud de dormitorio?',
    btnClear: 'Limpiar',
    btnSend: 'Enviar',
    chatSubtitle: 'Basado en documentos · Respuesta rápida',
  },
}

export type UILabels = typeof UI_LABELS.ko

export function getLabels(lang: string): UILabels {
  const key = (lang === 'auto' ? 'ko' : lang) as keyof typeof UI_LABELS
  return UI_LABELS[key] ?? UI_LABELS.ko
}
