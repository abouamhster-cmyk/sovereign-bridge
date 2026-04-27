"use client";
import { useState, useRef, useEffect } from "react";
import { 
  Send, ArrowLeft, Plus, Trash2, ChevronLeft, ChevronRight, 
  Search, Edit2, Check, X, Loader2, Menu
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

const API_URL = "https://sovereign-bridge.onrender.com";

type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type Message = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
};

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [filteredConversations, setFilteredConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false); // ← Fermée par défaut sur mobile
  const [isMobile, setIsMobile] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Détecter le mobile
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Charger les conversations
  useEffect(() => {
    fetchConversations();
  }, []);

  // Charger les messages quand une conversation change
  useEffect(() => {
    if (currentConversationId) {
      fetchMessages(currentConversationId);
    }
  }, [currentConversationId]);

  // Filtrer les conversations par recherche
  useEffect(() => {
    if (searchTerm.trim() === "") {
      setFilteredConversations(conversations);
    } else {
      const filtered = conversations.filter(conv => 
        conv.title.toLowerCase().includes(searchTerm.toLowerCase())
      );
      setFilteredConversations(filtered);
    }
  }, [searchTerm, conversations]);

  // Scroll auto vers le dernier message
  useEffect(() => {
    if (!isInitialLoad && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    } else {
      setIsInitialLoad(false);
    }
  }, [messages]);

  // Focus sur l'input après chargement
  useEffect(() => {
    if (currentConversationId && inputRef.current) {
      inputRef.current.focus();
    }
  }, [currentConversationId]);

  // Fermer la sidebar sur mobile quand on change de conversation
  useEffect(() => {
    if (isMobile) {
      setIsSidebarOpen(false);
    }
  }, [currentConversationId, isMobile]);

  async function fetchConversations() {
    const { data } = await supabase
      .from("conversations")
      .select("*")
      .order("updated_at", { ascending: false });
    
    setConversations(data || []);
    setFilteredConversations(data || []);
    
    if (!data || data.length === 0) {
      createNewConversation();
    } else if (!currentConversationId) {
      setCurrentConversationId(data[0].id);
    }
  }

  async function fetchMessages(conversationId: string) {
    const { data } = await supabase
      .from("conversation_messages")
      .select("*")
      .eq("conversation_id", conversationId)
      .order("created_at", { ascending: true });
    
    if (data && data.length > 0) {
      setMessages(data);
    } else {
      setMessages([{ role: "assistant", content: "Bonjour Rebecca. Que veux-tu qu'on attaque aujourd'hui ?" }]);
    }
  }

  async function createNewConversation() {
    const title = `Nouvelle conversation ${new Date().toLocaleDateString('fr-FR')}`;
    const { data, error } = await supabase
      .from("conversations")
      .insert({
        title: title,
        user_id: "rebecca"
      })
      .select()
      .single();
    
    if (!error && data) {
      setConversations(prev => [data, ...prev]);
      setFilteredConversations(prev => [data, ...prev]);
      setCurrentConversationId(data.id);
      setMessages([{ role: "assistant", content: "Bonjour Rebecca. Que veux-tu qu'on attaque aujourd'hui ?" }]);
      
      if (isMobile) setIsSidebarOpen(false);
    }
  }

  async function updateConversationTitle(id: string, newTitle: string) {
    if (!newTitle.trim()) return;
    
    const { error } = await supabase
      .from("conversations")
      .update({ title: newTitle })
      .eq("id", id);
    
    if (!error) {
      setConversations(prev => 
        prev.map(conv => conv.id === id ? { ...conv, title: newTitle } : conv)
      );
      setFilteredConversations(prev => 
        prev.map(conv => conv.id === id ? { ...conv, title: newTitle } : conv)
      );
    }
    setEditingTitleId(null);
    setEditingTitle("");
  }

  async function deleteConversation(id: string) {
    if (confirm("Supprimer cette conversation ?")) {
      const { error } = await supabase.from("conversations").delete().eq("id", id);
      if (!error) {
        const newConversations = conversations.filter(c => c.id !== id);
        setConversations(newConversations);
        setFilteredConversations(newConversations);
        
        if (newConversations.length > 0) {
          setCurrentConversationId(newConversations[0].id);
        } else {
          createNewConversation();
        }
      }
    }
  }

  async function saveMessage(conversationId: string, role: string, content: string) {
    await supabase.from("conversation_messages").insert({
      conversation_id: conversationId,
      role: role,
      content: content
    });
    
    await supabase
      .from("conversations")
      .update({ updated_at: new Date().toISOString() })
      .eq("id", conversationId);
  }

  const handleSend = async () => {
    if (!input.trim() || isLoading || !currentConversationId) return;
    
    const userMessage = { role: "user" as const, content: input };
    const allMessages = [...messages, userMessage];
    
    setMessages(prev => [...prev, userMessage]);
    await saveMessage(currentConversationId, "user", input);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          messages: allMessages.map(msg => ({
            role: msg.role,
            content: msg.content
          }))
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Erreur ${response.status}`);
      }
      
      const data = await response.json();
      const assistantContent = data.reply;
      
      setMessages(prev => [...prev, { role: "assistant", content: assistantContent }]);
      await saveMessage(currentConversationId, "assistant", assistantContent);
      
      fetchConversations();
      inputRef.current?.focus();
    } catch (error) {
      console.error("Erreur:", error);
      const errorMessage = "Erreur de connexion. Vérifie que le backend est bien démarré.";
      setMessages(prev => [...prev, { role: "assistant", content: errorMessage }]);
      await saveMessage(currentConversationId, "assistant", errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return "À l'instant";
    if (diffMins < 60) return `Il y a ${diffMins} min`;
    if (diffHours < 24) return `Il y a ${diffHours} h`;
    if (diffDays === 1) return "Hier";
    if (diffDays < 7) return `Il y a ${diffDays} jours`;
    return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
  };

  const startEditTitle = (conv: Conversation) => {
    setEditingTitleId(conv.id);
    setEditingTitle(conv.title);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="fixed inset-0 bg-midnight flex flex-col">
      {/* HEADER DU CHAT - AVEC BOUTON MENU */}
      <header className="sticky top-0 z-10 h-14 border-b border-white/10 flex items-center px-4 bg-midnight/90 backdrop-blur-lg shrink-0">
        <button
          onClick={() => setIsSidebarOpen(true)}
          className="p-2 text-gray-400 hover:text-gold-500 transition-colors rounded-lg hover:bg-white/5"
        >
          <Menu className="w-5 h-5" />
        </button>
        
        <div className="flex-1 text-center">
          <h1 className="text-base font-serif text-gold-500">SOVEREIGN AI</h1>
          <p className="text-[9px] text-gold-500/60 uppercase tracking-widest hidden sm:block">Executive Mode</p>
        </div>
        
        <button
          onClick={() => window.location.href = "/"}
          className="p-2 text-gray-400 hover:text-gold-500 transition-colors rounded-lg hover:bg-white/5"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
      </header>

      {/* SIDEBAR OVERLAY */}
      <AnimatePresence>
        {isSidebarOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsSidebarOpen(false)}
              className="fixed inset-0 bg-black/80 backdrop-blur-sm z-40"
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed inset-y-0 left-0 w-80 bg-midnight z-50 border-r border-white/10 flex flex-col"
            >
              <div className="p-4 border-b border-white/10 flex justify-between items-center">
                <h2 className="text-sm font-serif text-gold-500">Conversations</h2>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="p-1 text-gray-500 hover:text-gold-500 transition-colors"
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>
              </div>
              
              <div className="p-4">
                <button
                  onClick={createNewConversation}
                  className="w-full flex items-center justify-center gap-2 bg-gold-500/20 hover:bg-gold-500/30 text-gold-500 py-2 rounded-xl transition-colors text-sm"
                >
                  <Plus className="w-4 h-4" />
                  Nouvelle conversation
                </button>
              </div>
              
              <div className="px-4 pb-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="text"
                    placeholder="Rechercher..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-xl text-sm focus:outline-none focus:border-gold-500 text-ivory placeholder:text-gray-500"
                  />
                </div>
              </div>
              
              <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
                {filteredConversations.length === 0 ? (
                  <div className="text-center py-8 text-gray-500 text-sm">
                    {searchTerm ? "Aucune conversation trouvée" : "Aucune conversation"}
                  </div>
                ) : (
                  filteredConversations.map(conv => (
                    <div
                      key={conv.id}
                      className={`group p-3 rounded-xl cursor-pointer transition-all ${
                        currentConversationId === conv.id
                          ? "bg-gold-500/10 border border-gold-500/30"
                          : "hover:bg-white/5 border border-transparent"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div 
                          onClick={() => setCurrentConversationId(conv.id)}
                          className="flex-1 min-w-0"
                        >
                          {editingTitleId === conv.id ? (
                            <div className="flex items-center gap-2">
                              <input
                                type="text"
                                value={editingTitle}
                                onChange={(e) => setEditingTitle(e.target.value)}
                                className="flex-1 bg-white/10 border border-gold-500 rounded-md px-2 py-1 text-sm focus:outline-none"
                                autoFocus
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') updateConversationTitle(conv.id, editingTitle);
                                  if (e.key === 'Escape') setEditingTitleId(null);
                                }}
                              />
                              <button onClick={() => updateConversationTitle(conv.id, editingTitle)} className="text-emerald-400">
                                <Check className="w-3 h-3" />
                              </button>
                              <button onClick={() => setEditingTitleId(null)} className="text-red-400">
                                <X className="w-3 h-3" />
                              </button>
                            </div>
                          ) : (
                            <>
                              <p className="text-sm truncate">{conv.title || "Nouvelle conversation"}</p>
                              <p className="text-xs text-gray-500 mt-1">{formatDate(conv.updated_at)}</p>
                            </>
                          )}
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              startEditTitle(conv);
                            }}
                            className="p-1 text-gray-500 hover:text-gold-500 transition-colors"
                          >
                            <Edit2 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteConversation(conv.id);
                            }}
                            className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* ZONE DES MESSAGES - SCROLLABLE */}
      <div 
        ref={messagesContainerRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
      >
        {messages.map((m, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div className={`max-w-[85%] p-4 rounded-2xl text-sm leading-relaxed ${
              m.role === "user" 
                ? "bg-gold-500 text-midnight rounded-br-none" 
                : "bg-white/10 text-ivory border border-white/5 rounded-bl-none"
            }`}>
              {m.content}
            </div>
          </motion.div>
        ))}
        
        {isLoading && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex justify-start"
          >
            <div className="bg-white/10 p-4 rounded-2xl rounded-bl-none">
              <Loader2 className="w-4 h-4 text-gold-500 animate-spin" />
            </div>
          </motion.div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* BARRE DE SAISIE - FIXE EN BAS */}
      <div className="shrink-0 p-4 border-t border-white/10 bg-midnight/90 backdrop-blur-lg">
        <div className="relative max-w-4xl mx-auto flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Écris ton message... (Entrée pour envoyer)"
            className="flex-1 bg-white/10 border border-white/20 rounded-full py-3 px-5 pr-12 text-sm focus:outline-none focus:border-gold-500 transition-all text-ivory placeholder:text-gray-500"
          />
          <button 
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="absolute right-2 p-2 bg-gold-500 rounded-full text-midnight hover:scale-105 transition-transform disabled:opacity-50 disabled:hover:scale-100"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
