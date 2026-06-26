import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchProjects, createProject, deleteProject } from '../api'

function ProjectList({ onSelectProject }) {
  const [projects, setProjects] = useState([])
  const [showModal, setShowModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectGoal, setNewProjectGoal] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    try {
      const data = await fetchProjects()
      setProjects(data)
      setError(null)
    } catch (err) {
      setError(`Failed to load projects: ${err.message}`)
    }
  }

  const handleCreateProject = async (e) => {
    e.preventDefault()
    if (!newProjectName.trim()) return

    setIsLoading(true)
    try {
      const project = await createProject(newProjectName.trim(), newProjectGoal.trim())
      setProjects([...projects, project])
      setShowModal(false)
      setNewProjectName('')
      setNewProjectGoal('')
      onSelectProject(project)
    } catch (err) {
      setError(`Failed to create project: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDeleteProject = async (e, projectId) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this project?')) return

    try {
      await deleteProject(projectId)
      setProjects(projects.filter(p => p.id !== projectId))
    } catch (err) {
      setError(`Failed to delete project: ${err.message}`)
    }
  }

  const handleProjectClick = (project) => {
    onSelectProject(project)
  }

  const formatDate = (dateString) => {
    const date = new Date(dateString)
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="project-list-container">
      <div className="project-list-header">
        <h2>CMV Projects</h2>
        <button className="new-button" onClick={() => setShowModal(true)}>
          + New Project
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {projects.length === 0 ? (
        <div className="empty-state">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#ccc" strokeWidth="1.5">
            <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          <p>No projects yet. Create one to get started!</p>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map(project => (
            <div
              key={project.id}
              className="project-card"
              onClick={() => handleProjectClick(project)}
            >
              <div className="project-card-header">
                <h3>{project.name}</h3>
                <button
                  className="delete-button"
                  onClick={(e) => handleDeleteProject(e, project.id)}
                  title="Delete project"
                >
                  ×
                </button>
              </div>
              <p className="project-goal">
                {project.goal || 'No goal set'}
              </p>
              <div className="project-meta">
                <span>Created: {formatDate(project.created_at)}</span>
                <span>Updated: {formatDate(project.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create New Project</h3>
              <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <form onSubmit={handleCreateProject}>
              <div className="form-group">
                <label>Project Name</label>
                <input
                  type="text"
                  value={newProjectName}
                  onChange={e => setNewProjectName(e.target.value)}
                  placeholder="Enter project name..."
                  autoFocus
                />
              </div>
              <div className="form-group">
                <label>Project Goal (optional)</label>
                <textarea
                  value={newProjectGoal}
                  onChange={e => setNewProjectGoal(e.target.value)}
                  placeholder="Describe the project goal..."
                  rows={4}
                />
              </div>
              <div className="modal-actions">
                <button type="button" className="cancel-button" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="submit-button" disabled={isLoading || !newProjectName.trim()}>
                  {isLoading ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default ProjectList
