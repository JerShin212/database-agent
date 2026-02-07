import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/shared/Layout'
import ChatPage from './pages/ChatPage'
import CollectionsPage from './pages/CollectionsPage'
import DatabasesPage from './pages/DatabasesPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<ChatPage />} />
          <Route path="collections" element={<CollectionsPage />} />
          <Route path="databases" element={<DatabasesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
