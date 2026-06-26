function ProjectInfoSection({
  project,
  isEditing,
  editName,
  editGoal,
  onStartEdit,
  onCancel,
  onSave,
  onNameChange,
  onGoalChange
}) {
  if (!project) return null

  return (
    <div className="project-info-section">
      <div className="section-header">
        <h2>Project Information</h2>
        {!isEditing && (
          <button className="edit-button" onClick={onStartEdit}>
            Edit
          </button>
        )}
      </div>

      {isEditing ? (
        <div className="edit-form">
          <div className="form-group">
            <label>Project Name</label>
            <input
              type="text"
              value={editName}
              onChange={e => onNameChange(e.target.value)}
              placeholder="Project name..."
            />
          </div>
          <div className="form-group">
            <label>Project Goal</label>
            <textarea
              value={editGoal}
              onChange={e => onGoalChange(e.target.value)}
              placeholder="Describe the project goal..."
              rows={4}
            />
          </div>
          <div className="edit-actions">
            <button className="cancel-button" onClick={onCancel}>Cancel</button>
            <button className="save-button" onClick={onSave}>Save</button>
          </div>
        </div>
      ) : (
        <div className="project-info-display">
          <div className="info-item">
            <label>Name:</label>
            <span>{project.name}</span>
          </div>
          <div className="info-item">
            <label>Goal:</label>
            <span>{project.goal || 'No goal set'}</span>
          </div>
          <div className="info-item">
            <label>Created:</label>
            <span>{new Date(project.created_at).toLocaleString()}</span>
          </div>
          <div className="info-item">
            <label>Updated:</label>
            <span>{new Date(project.updated_at).toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default ProjectInfoSection
