import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import ProjectList from './interfaces/ProjectList'
import ProjectDetail from './interfaces/ProjectDetail'
import './index.css'

function Home() {
  const navigate = useNavigate()

  const handleSelectProject = (project) => {
    navigate(`/project/${project.id}`)
  }

  return <ProjectList onSelectProject={handleSelectProject} />
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/project/:projectId" element={<ProjectDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App
