import ValueRange from './ValueRange'

function DatabaseSection({
  databases,
  expandedDb,
  isUploading,
  onUpload,
  onDelete,
  onToggleExpand,
  fileInputRef
}) {
  return (
    <div className="databases-section">
      <div className="section-header">
        <h2>Databases</h2>
        <div className="upload-section">
          <input
            type="file"
            ref={fileInputRef}
            onChange={onUpload}
            accept=".db,.sqlite,.sqlite3,.csv"
            multiple
            style={{ display: 'none' }}
          />
          <button
            className="upload-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            {isUploading ? 'Uploading...' : '+ Upload Database'}
          </button>
        </div>
      </div>

      {databases.length === 0 ? (
        <div className="empty-databases">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ccc" strokeWidth="1.5">
            <ellipse cx="12" cy="5" rx="9" ry="3" />
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
          </svg>
          <p>No databases uploaded yet</p>
          <span>Upload .db, .sqlite, .sqlite3 or .csv files</span>
        </div>
      ) : (
        <div className="databases-list">
          {databases.map(db => (
            <div key={db.db_name} className="database-item">
              <div className="database-header" onClick={() => onToggleExpand(db.db_name)}>
                <div className="database-info">
                  <span className="expand-icon">{expandedDb === db.db_name ? '▼' : '▶'}</span>
                  <span className="db-name">{db.db_name}</span>
                  <span className="table-count">{db.tables.length} tables</span>
                </div>
                <button
                  className="delete-db-button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(db.db_name)
                  }}
                  title="Delete database"
                >
                  ×
                </button>
              </div>

              {expandedDb === db.db_name && (
                <div className="database-details">
                  <p className="upload-time">Uploaded: {new Date(db.uploaded_at).toLocaleString()}</p>
                  <div className="tables-list">
                    {db.tables.map(table => (
                      <div key={table.table_name} className="table-item">
                        <div className="table-header">
                          <span className="table-name">{table.table_name}</span>
                          <span className="row-count">{table.row_count} rows</span>
                        </div>
                        <div className="columns-list">
                          {table.columns.map(col => (
                            <div key={col.column_name} className="column-item">
                              <span className="column-name">
                                {col.column_name}
                                {col.is_primary_key && <span className="pk-badge">PK</span>}
                              </span>
                              <span className="column-type">{col.data_type}</span>
                              <ValueRange valueRange={col.value_range} dataType={col.data_type} />
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default DatabaseSection
