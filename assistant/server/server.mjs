import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const port = Number(process.env.PORT || 8787);
const apiKey = process.env.DEEPSEEK_API_KEY;
const model = process.env.DEEPSEEK_MODEL || 'deepseek-flash';
const localRagEnabled = process.env.LOCAL_RAG_ENABLED === 'true';
const root = path.dirname(fileURLToPath(import.meta.url));
const knowledgeRoot = path.join(root, '..', 'knowledge');

const headers = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Content-Type': 'application/json; charset=utf-8'
};

function send(res, status, body) { res.writeHead(status, headers); res.end(JSON.stringify(body)); }
function readBody(req) { return new Promise((resolve, reject) => { let data=''; req.on('data', chunk => { data += chunk; if (data.length > 1_000_000) req.destroy(); }); req.on('end', () => resolve(data)); req.on('error', reject); }); }

function loadKnowledge() {
  if (!fs.existsSync(knowledgeRoot)) return [];
  return fs.readdirSync(knowledgeRoot).filter(name => name.endsWith('.md')).flatMap(name => {
    const text = fs.readFileSync(path.join(knowledgeRoot, name), 'utf8');
    return text.split(/\n(?=##?\s)/).map((chunk, index) => ({ source: name, index, text: chunk.trim() })).filter(item => item.text);
  });
}

function retrieveKnowledge(question, limit = 8) {
  const raw = question.toLowerCase().match(/[\u4e00-\u9fff]+|[a-z0-9_]{2,}/g) || [];
  const terms = [...new Set(raw.flatMap(part => /[\u4e00-\u9fff]/.test(part) ? [...part].flatMap((_, i) => i < part.length - 1 ? [part.slice(i, i + 2)] : []) : [part]))];
  return loadKnowledge().map(item => ({ ...item, score: terms.reduce((sum, term) => sum + (item.text.toLowerCase().includes(term) ? 1 : 0), 0) }))
    .filter(item => item.score > 0).sort((a, b) => b.score - a.score).slice(0, limit);
}

async function retrieveWithLocalEmbedding(question) {
  try {
    const response = await fetch('http://127.0.0.1:8790/retrieve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 11 }),
      signal: AbortSignal.timeout(8000)
    });
    if (!response.ok) return null;
    const result = await response.json();
    return Array.isArray(result.results) ? result.results : null;
  } catch (error) {
    console.warn(`Local RAG unavailable: ${error.message}`);
    return null;
  }
}

function needsKnowledge(question) {
  return /CRM|字段|导出|规则|口径|评分|得分|虚假拜访|质检|站长|省区|问题类型|客户|拜访|Excel|上传|报错|通报/i.test(question);
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') { res.writeHead(204, headers); return res.end(); }
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) { res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'}); return res.end(fs.readFileSync(path.join(root, '..', 'index.html'))); }
  if (req.method !== 'POST' || req.url !== '/api/chat') return send(res, 404, { error: 'Not found' });
  if (!apiKey) return send(res, 503, { error: '后端尚未配置 DEEPSEEK_API_KEY' });
  try {
    const body = JSON.parse(await readBody(req));
    const question = typeof body.question === 'string' ? body.question.trim() : '';
    if (!question) return send(res, 400, { error: 'question 必须是非空字符串' });
    const context = typeof body.context === 'string' ? body.context.slice(0, 12000) : '';
    const useKnowledge = needsKnowledge(question);
    const vectorKnowledge = useKnowledge && localRagEnabled ? await retrieveWithLocalEmbedding(question) : null;
    const knowledge = useKnowledge ? (vectorKnowledge?.length ? vectorKnowledge : retrieveKnowledge(question)) : [];
    const knowledgeContext = knowledge.length ? knowledge.map((item, i) => `[资料${i + 1}｜${item.source}]\n${item.text}`).join('\n\n') : '';
    const system = '你是省区虚假拜访质量分析助手。只解释和分析CRM已识别的质检问题，不自行判断站长是否虚假，不查看照片，不编造统计结果。数据统计应优先相信调用方提供的确定性分析结果；不确定时明确说明。回答简洁、先给结论。';
    const promptParts = [];
    if (context) promptParts.push(`当前分析结果（来自本地确定性程序）：\n${context}`);
    if (knowledgeContext) promptParts.push(`相关业务资料（只依据这些资料回答规则类问题）：\n${knowledgeContext}`);
    promptParts.push(`用户问题：${question}`);
    const response = await fetch('https://api.deepseek.com/chat/completions', { method:'POST', headers:{'Authorization':`Bearer ${apiKey}`,'Content-Type':'application/json'}, body:JSON.stringify({ model, messages:[{role:'system',content:system},{role:'user',content:promptParts.join('\n\n')}], stream:false, thinking:{type:'disabled'}, max_tokens:1200 }) });
    const result = await response.json();
    if (!response.ok) return send(res, response.status, { error: result?.error?.message || 'DeepSeek API 调用失败' });
    send(res, 200, { answer: result?.choices?.[0]?.message?.content || '', sources: [...new Set(knowledge.map(item => item.source))], retrieval: vectorKnowledge?.length ? 'local_embedding' : 'keyword_fallback' });
  } catch (error) { send(res, 500, { error: '服务端处理失败' }); }
});

server.listen(port, () => console.log(`Quality assistant API listening on http://localhost:${port}`));
