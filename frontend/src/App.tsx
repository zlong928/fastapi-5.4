import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { DashboardPage } from "@/pages/DashboardPage";
import { DocumentDetailPage } from "@/pages/DocumentDetailPage";
import { ChatPage } from "@/pages/ChatPage";
import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { LoginPage } from "@/pages/LoginPage";
import { NotesPage } from "@/pages/NotesPage";
import { OAuthCallbackPage } from "@/pages/OAuthCallbackPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { ResetPasswordPage } from "@/pages/ResetPasswordPage";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { TasksPage } from "@/pages/TasksPage";

export function App() {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5_000 } } }));

  return (
    <QueryClientProvider client={queryClient}>
      <Layout>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
          <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/knowledge" element={<ProtectedRoute><KnowledgePage /></ProtectedRoute>} />
          <Route path="/documents/:id" element={<ProtectedRoute><DocumentDetailPage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
          <Route path="/notes" element={<ProtectedRoute><NotesPage /></ProtectedRoute>} />
          <Route path="/search" element={<ProtectedRoute><SearchPage /></ProtectedRoute>} />
          <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
          <Route path="/tasks" element={<ProtectedRoute><TasksPage /></ProtectedRoute>} />
          <Route path="/tasks/:id" element={<ProtectedRoute><TaskDetailPage /></ProtectedRoute>} />
          <Route path="/upload" element={<ProtectedRoute><Navigate to="/knowledge?upload=1" replace /></ProtectedRoute>} />
          <Route path="/documents" element={<ProtectedRoute><Navigate to="/knowledge" replace /></ProtectedRoute>} />
          <Route path="/tags" element={<ProtectedRoute><Navigate to="/knowledge?tab=tags" replace /></ProtectedRoute>} />
          <Route path="/tools" element={<ProtectedRoute><Navigate to="/knowledge" replace /></ProtectedRoute>} />
          <Route path="/books" element={<ProtectedRoute><Navigate to="/knowledge?type=epub" replace /></ProtectedRoute>} />
          <Route path="/books/:bookId/reader" element={<ProtectedRoute><Navigate to="/knowledge?type=epub" replace /></ProtectedRoute>} />
          <Route path="/statistics" element={<ProtectedRoute><Navigate to="/" replace /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </QueryClientProvider>
  );
}
