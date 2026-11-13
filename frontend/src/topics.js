// Each topic sets --topic (see index.css), so `text-topic`, `bg-topic/12` and
// `border-topic` pick up its colour anywhere inside.
const CLASS = { Geopolitics: 't-geo', Sports: 't-sports', Economics: 't-econ', Technology: 't-tech' }

export const topicClass = (topic) => CLASS[topic] ?? ''
