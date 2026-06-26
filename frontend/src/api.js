const API_BASE = '/api';

async function fetchModels() {
  const response = await fetch(`${API_BASE}/models`);
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function setModel(modelName) {
  const response = await fetch(`${API_BASE}/model/set`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName })
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function sendMessage(message, temperature = 0.7) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, temperature })
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function clearConversation() {
  const response = await fetch(`${API_BASE}/conversation/clear`, {
    method: 'POST'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data;
}

async function checkHealth() {
  const response = await fetch(`${API_BASE}/health`);
  return response.json();
}

// ========== 项目管理 API ==========

async function fetchProjects() {
  const response = await fetch(`${API_BASE}/projects`);
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function createProject(name, goal = '') {
  const response = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, goal })
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getProject(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}`);
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function updateProject(projectId, updates) {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function deleteProject(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'DELETE'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data;
}

// ========== 数据库管理 API ==========

async function fetchDatabases(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/databases`);
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function uploadDatabase(projectId, file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/projects/${projectId}/databases`, {
    method: 'POST',
    body: formData
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function deleteDatabase(projectId, dbName) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/databases/${dbName}`, {
    method: 'DELETE'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data;
}

// ========== Plan 生成 API ==========

async function generateGoal(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/plan/generate-goal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function generatePlan(projectId, context = '') {
  const response = await fetch(`${API_BASE}/projects/${projectId}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context })
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getPlan(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/plan`, {
    method: 'GET'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

// ========== Data Processing API ==========

async function processData(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/data/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function processSingleDNode(projectId, nodeId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/data/process/node/${nodeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getNodeData(projectId, nodeId, limit = 50) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/data/${nodeId}?limit=${limit}`, {
    method: 'GET'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getNodeCode(projectId, nodeId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/data/${nodeId}/code`, {
    method: 'GET'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getDataResult(projectId) {
  try {
    const response = await fetch(`${API_BASE}/projects/${projectId}/data/process/result`, {
      method: 'GET'
    });
    const data = await response.json();
    if (!data.success) throw new Error(data.error);
    return data.data;
  } catch (err) {
    return null;
  }
}

// ========== Visualization API ==========

async function processVisualizations(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/vis/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function processSingleVNode(projectId, nodeId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/vis/process/node/${nodeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getVisSpec(projectId, nodeId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/vis/${nodeId}`, {
    method: 'GET'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
  return data.data;
}

async function getAgentTrace(projectId) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/agents/trace`, {
    method: 'GET'
  });
  const data = await response.json();
  if (!data.success) throw new Error(data.error);
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
  getAgentTrace
};
