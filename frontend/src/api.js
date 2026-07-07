const DEFAULT_API_BASES = [
  'http://10.2.0.2:5000/api',
  'http://127.0.0.1:5000/api',
  'http://localhost:5000/api',
  '/api'
];

const API_BASES = import.meta.env.VITE_API_BASE_URL
  ? [import.meta.env.VITE_API_BASE_URL, ...DEFAULT_API_BASES]
  : DEFAULT_API_BASES;

const UNIQUE_API_BASES = [...new Set(API_BASES.map(normalizeApiBase))];

function normalizeApiBase(apiBase) {
  return apiBase.replace(/\/$/, '');
}

function fallbackError(message) {
  const error = new Error(message);
  error.canFallback = true;
  return error;
}

function backendConnectionError(apiBase) {
  return fallbackError(
    `Cannot connect to the backend service at ${apiBase}. ` +
    'Make sure the backend is running and set VITE_API_BASE_URL if it uses another host or port.'
  );
}

async function requestJsonFrom(apiBase, path, options = {}) {
  const normalizedApiBase = normalizeApiBase(apiBase);
  let response;
  try {
    response = await fetch(`${normalizedApiBase}${path}`, options);
  } catch (error) {
    throw backendConnectionError(normalizedApiBase);
  }

  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw fallbackError(`The backend returned an invalid response from ${normalizedApiBase}${path} (HTTP ${response.status}).`);
  }

  if (response.status === 404) {
    throw fallbackError(
      `Backend endpoint not found: ${normalizedApiBase}${path}. ` +
      'The frontend reached a server, but it does not expose the expected CMV API routes. ' +
      'Check that you started the matching backend app.py, or set VITE_API_BASE_URL to the correct backend URL.'
    );
  }

  if (!response.ok || data.success === false) {
    throw new Error(data.error || `Request to ${normalizedApiBase}${path} failed (HTTP ${response.status}).`);
  }

  return data;
}

async function requestJson(path, options = {}) {
  const errors = [];

  for (const apiBase of UNIQUE_API_BASES) {
    try {
      return await requestJsonFrom(apiBase, path, options);
    } catch (error) {
      errors.push(error.message);
      if (!error.canFallback) {
        throw error;
      }
    }
  }

  throw new Error(errors.join(' | '));
}

async function fetchModels() {
  const data = await requestJson('/models');
  return data.data;
}

async function setModel(modelName) {
  const data = await requestJson('/model/set', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName })
  });
  return data.data;
}

async function sendMessage(message, temperature = 0.7) {
  const data = await requestJson('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, temperature })
  });
  return data.data;
}

async function clearConversation() {
  const data = await requestJson('/conversation/clear', {
    method: 'POST'
  });
  return data;
}

async function checkHealth() {
  return requestJson('/health');
}

// ========== 项目管理 API ==========

async function fetchProjects() {
  const data = await requestJson('/projects');
  return data.data;
}

async function createProject(name, goal = '') {
  const data = await requestJson('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, goal })
  });
  return data.data;
}

async function getProject(projectId) {
  const data = await requestJson(`/projects/${projectId}`);
  return data.data;
}

async function updateProject(projectId, updates) {
  const data = await requestJson(`/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  return data.data;
}

async function deleteProject(projectId) {
  const data = await requestJson(`/projects/${projectId}`, {
    method: 'DELETE'
  });
  return data;
}

// ========== 数据库管理 API ==========

async function fetchDatabases(projectId) {
  const data = await requestJson(`/projects/${projectId}/databases`);
  return data.data;
}

async function uploadDatabase(projectId, file) {
  const formData = new FormData();
  formData.append('file', file);

  const data = await requestJson(`/projects/${projectId}/databases`, {
    method: 'POST',
    body: formData
  });
  return data.data;
}

async function deleteDatabase(projectId, dbName) {
  const data = await requestJson(`/projects/${projectId}/databases/${dbName}`, {
    method: 'DELETE'
  });
  return data;
}

// ========== Plan 生成 API ==========

async function generateGoal(projectId) {
  const data = await requestJson(`/projects/${projectId}/plan/generate-goal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function generatePlan(projectId, context = '') {
  const data = await requestJson(`/projects/${projectId}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context })
  });
  return data.data;
}

async function getPlan(projectId) {
  const data = await requestJson(`/projects/${projectId}/plan`, {
    method: 'GET'
  });
  return data.data;
}

// ========== Data Processing API ==========

async function processData(projectId) {
  const data = await requestJson(`/projects/${projectId}/data/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function processSingleDNode(projectId, nodeId) {
  const data = await requestJson(`/projects/${projectId}/data/process/node/${nodeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function getNodeData(projectId, nodeId, limit = 50) {
  const data = await requestJson(`/projects/${projectId}/data/${nodeId}?limit=${limit}`, {
    method: 'GET'
  });
  return data.data;
}

async function getNodeCode(projectId, nodeId) {
  const data = await requestJson(`/projects/${projectId}/data/${nodeId}/code`, {
    method: 'GET'
  });
  return data.data;
}

async function getDataResult(projectId) {
  try {
    const data = await requestJson(`/projects/${projectId}/data/process/result`, {
      method: 'GET'
    });
    return data.data;
  } catch (err) {
    return null;
  }
}

// ========== Visualization API ==========

async function processVisualizations(projectId) {
  const data = await requestJson(`/projects/${projectId}/vis/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function processSingleVNode(projectId, nodeId) {
  const data = await requestJson(`/projects/${projectId}/vis/process/node/${nodeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function getVisSpec(projectId, nodeId) {
  const data = await requestJson(`/projects/${projectId}/vis/${nodeId}`, {
    method: 'GET'
  });
  return data.data;
}

async function getAgentTrace(projectId) {
  const data = await requestJson(`/projects/${projectId}/agents/trace`, {
    method: 'GET'
  });
  return data.data;
}

async function processInteractions(projectId) {
  const data = await requestJson(`/projects/${projectId}/interactions/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return data.data;
}

async function getDataFlow(projectId) {
  const data = await requestJson(`/projects/${projectId}/planner/data-flow`, {
    method: 'GET'
  });
  return data.data;
}

async function resetProcessing(projectId) {
  const data = await requestJson(`/projects/${projectId}/reset-processing`, {
    method: 'POST'
  });
  return data;
}

async function getTrace(projectId) {
  const data = await requestJson(`/projects/${projectId}/trace`, {
    method: 'GET'
  });
  return data.data;
}

async function getInteractionResult(projectId, nodeId) {
  const data = await requestJson(`/projects/${projectId}/interactions/${nodeId}`, {
    method: 'GET'
  });
  return data.data;
}

export {
  fetchModels,
  setModel,
  sendMessage,
  clearConversation,
  checkHealth,
  fetchProjects,
  createProject,
  getProject,
  updateProject,
  deleteProject,
  fetchDatabases,
  uploadDatabase,
  deleteDatabase,
  generateGoal,
  generatePlan,
  getPlan,
  processData,
  processSingleDNode,
  getNodeData,
  getNodeCode,
  getDataResult,
  processVisualizations,
  processSingleVNode,
  getVisSpec,
  getAgentTrace,
  processInteractions,
  getDataFlow,
  getInteractionResult,
  getTrace,
  resetProcessing
};
