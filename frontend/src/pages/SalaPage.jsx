import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { formatBytes, timeAgo } from '../utils';
import FeedPage from './FeedPage';

function userAvatar(url, initials) {
  if (url) {
    return <img src={api.assetUrl(url)} alt="" style={{ width: 24, height: 24, borderRadius: '50%', objectFit: 'cover' }} />;
  }
  return (
    <div style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--gold)', color: '#fff', fontSize: 10, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {(initials || '?').slice(0, 2)}
    </div>
  );
}

export default function SalaPage() {
  const { user, allUsers } = useAuth();
  const toast = useToast();

  const [rooms, setRooms] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loadingRooms, setLoadingRooms] = useState(true);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newPrivate, setNewPrivate] = useState(false);

  const [activeTab, setActiveTab] = useState('chat');
  const [messages, setMessages] = useState([]);
  const [messageText, setMessageText] = useState('');
  const [sending, setSending] = useState(false);
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [members, setMembers] = useState([]);
  const [selectedMemberKey, setSelectedMemberKey] = useState('');
  const [joiningCall, setJoiningCall] = useState(false);
  const [showCall, setShowCall] = useState(false);
  const bottomRef = useRef(null);

  const selectedRoom = useMemo(() => rooms.find(r => r.id === selectedId) || null, [rooms, selectedId]);
  const roomChannel = selectedRoom ? `sala_${selectedRoom.id}` : '';
  const canManageMembers = !!(selectedRoom && (selectedRoom.created_by === user?.key || user?.is_admin || user?.is_admin_user));

  useEffect(() => { loadRooms(); }, []);
  useEffect(() => {
    if (!selectedRoom) return;
    if (activeTab === 'chat') loadChat();
    if (activeTab === 'files') loadFiles();
    if (activeTab === 'members') loadMembers();
  }, [selectedId, activeTab]);
  useEffect(() => {
    if (activeTab !== 'chat' || !selectedRoom) return;
    const timer = setInterval(loadChat, 3000);
    return () => clearInterval(timer);
  }, [activeTab, selectedId]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function loadRooms() {
    setLoadingRooms(true);
    try {
      const data = await api.getSocialRooms();
      setRooms(data);
      if (!selectedId && data.length) setSelectedId(data[0].id);
      if (selectedId && !data.find(r => r.id === selectedId)) setSelectedId(data[0]?.id || null);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoadingRooms(false);
    }
  }

  async function createRoom() {
    if (!newName.trim()) return toast('Digite o nome da sala.', 'error');
    setCreating(true);
    try {
      await api.createSocialRoom({
        name: newName,
        description: newDescription,
        is_private: newPrivate,
        member_keys: []
      });
      setNewName('');
      setNewDescription('');
      setNewPrivate(false);
      await loadRooms();
      toast('Sala criada!', 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setCreating(false);
    }
  }

  async function removeRoom(room) {
    if (!confirm(`Remover a sala "${room.name}"?`)) return;
    try {
      await api.deleteSocialRoom(room.id);
      setSelectedId(null);
      await loadRooms();
      toast('Sala removida.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function loadChat() {
    if (!roomChannel) return;
    try {
      const data = await api.getChat(roomChannel);
      setMessages(data);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function sendMessage() {
    if (!roomChannel || !messageText.trim() || sending) return;
    setSending(true);
    try {
      await api.sendChat(roomChannel, messageText.trim());
      setMessageText('');
      await loadChat();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSending(false);
    }
  }

  async function loadFiles() {
    if (!selectedRoom) return;
    try {
      const data = await api.getSocialRoomFiles(selectedRoom.id);
      setFiles(data);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function uploadFiles(e) {
    if (!selectedRoom) return;
    const incoming = Array.from(e.target.files || []);
    if (!incoming.length) return;
    setUploading(true);
    try {
      for (const f of incoming) {
        await api.uploadSocialRoomFile(selectedRoom.id, f);
      }
      await loadFiles();
      toast('Arquivo(s) enviado(s)!', 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  async function removeFile(fileId) {
    if (!selectedRoom) return;
    if (!confirm('Remover este arquivo?')) return;
    try {
      await api.deleteSocialRoomFile(selectedRoom.id, fileId);
      setFiles(prev => prev.filter(f => f.id !== fileId));
      toast('Arquivo removido.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function loadMembers() {
    if (!selectedRoom) return;
    try {
      const data = await api.getSocialRoomMembers(selectedRoom.id);
      setMembers(data.members || []);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function addMember() {
    if (!selectedRoom || !selectedMemberKey) return;
    try {
      await api.addSocialRoomMember(selectedRoom.id, selectedMemberKey);
      setSelectedMemberKey('');
      await loadMembers();
      await loadRooms();
      toast('Participante adicionado.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function removeMember(userKey) {
    if (!selectedRoom) return;
    if (!confirm('Remover este participante da sala?')) return;
    try {
      await api.removeSocialRoomMember(selectedRoom.id, userKey);
      await loadMembers();
      await loadRooms();
      toast('Participante removido.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function openVoiceCall() {
    if (!selectedRoom) return;
    setJoiningCall(true);
    setTimeout(() => {
      setShowCall(true);
      setJoiningCall(false);
    }, 300);
  }

  const jitsiUrl = selectedRoom
    ? `https://meet.jit.si/dialogos-sala-${selectedRoom.id}?config.startWithAudioMuted=false#userInfo.displayName=${encodeURIComponent(user?.name || 'Colaborador')}`
    : '';

  const canDeleteRoom = !!(selectedRoom && (selectedRoom.created_by === user?.key || user?.is_admin || user?.is_admin_user));
  const availableUsers = Object.values(allUsers || {}).filter(u => !members.some(m => m.user_key === u.key));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16 }}>
      <div className="surface-card" style={{ padding: 14, height: 'calc(100vh - 110px)', overflow: 'auto' }}>
        <div className="section-title" style={{ fontSize: 20, marginBottom: 6 }}>Sala</div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          Grupos de conversa, posts e arquivos.
        </p>

        <div style={{ display: 'grid', gap: 6, marginBottom: 12 }}>
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Nome da nova sala"
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}
          />
          <input
            value={newDescription}
            onChange={e => setNewDescription(e.target.value)}
            placeholder="Descrição (opcional)"
            style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}
          />
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={newPrivate} onChange={e => setNewPrivate(e.target.checked)} />
            Sala privada (somente participantes)
          </label>
          <button className="btn-admin btn-primary" onClick={createRoom} disabled={creating}>
            {creating ? 'Criando...' : '+ Criar Sala'}
          </button>
        </div>

        {loadingRooms && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Carregando salas...</div>}
        {!loadingRooms && rooms.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Nenhuma sala criada ainda.</div>
        )}

        <div style={{ display: 'grid', gap: 8 }}>
          {rooms.map(room => (
            <div
              key={room.id}
              onClick={() => { setSelectedId(room.id); setActiveTab('chat'); }}
              style={{
                border: `1px solid ${selectedId === room.id ? 'var(--gold)' : 'var(--border)'}`,
                borderRadius: 10,
                padding: '10px 10px',
                background: selectedId === room.id ? 'rgba(201,168,76,0.1)' : 'var(--bg)',
                cursor: 'pointer'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{room.name}</div>
                {room.is_private ? <span style={{ fontSize: 10, color: 'var(--gold)' }}>Privada</span> : <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Pública</span>}
              </div>
              {!!room.description && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{room.description}</div>}
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                {room.members_count || 0} pessoa(s) · {room.files_count || 0} arquivo(s)
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        {!selectedRoom ? (
          <div className="surface-card" style={{ padding: 20 }}>
            <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Selecione uma sala para começar.</div>
          </div>
        ) : (
          <>
            <div className="surface-card" style={{ padding: 14, marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                  <div className="section-title" style={{ marginBottom: 4 }}>{selectedRoom.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{selectedRoom.description || 'Sem descrição'}</div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn-admin btn-secondary" onClick={openVoiceCall} disabled={joiningCall}>
                    {joiningCall ? 'Entrando...' : '🔊 Chamada de Voz'}
                  </button>
                  {canDeleteRoom && (
                    <button className="btn-admin btn-danger" onClick={() => removeRoom(selectedRoom)}>🗑 Remover Sala</button>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <button className="btn-admin btn-secondary" style={activeTab === 'chat' ? { borderColor: 'var(--gold)', color: 'var(--gold)' } : {}} onClick={() => setActiveTab('chat')}>Conversa</button>
                <button className="btn-admin btn-secondary" style={activeTab === 'posts' ? { borderColor: 'var(--gold)', color: 'var(--gold)' } : {}} onClick={() => setActiveTab('posts')}>Posts</button>
                <button className="btn-admin btn-secondary" style={activeTab === 'files' ? { borderColor: 'var(--gold)', color: 'var(--gold)' } : {}} onClick={() => setActiveTab('files')}>Arquivos</button>
                <button className="btn-admin btn-secondary" style={activeTab === 'members' ? { borderColor: 'var(--gold)', color: 'var(--gold)' } : {}} onClick={() => setActiveTab('members')}>Participantes</button>
              </div>
            </div>

            {activeTab === 'chat' && (
              <div className="surface-card" style={{ padding: 14 }}>
                <div style={{ border: '1px solid var(--border)', borderRadius: 10, minHeight: 360, maxHeight: 520, overflowY: 'auto', padding: 10, background: 'var(--bg)' }}>
                  {messages.length === 0 && (
                    <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', marginTop: 30 }}>
                      Nenhuma mensagem ainda. Comece a conversa da sala.
                    </div>
                  )}
                  {messages.map(msg => {
                    const mine = msg.sender_key === user?.key;
                    return (
                      <div key={msg.id} style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
                        <div style={{ maxWidth: '75%', background: mine ? 'var(--gold)' : 'var(--surface)', color: mine ? '#fff' : 'var(--text)', border: mine ? 'none' : '1px solid var(--border)', borderRadius: 12, padding: '8px 10px' }}>
                          <div style={{ fontSize: 11, opacity: 0.85, marginBottom: 2 }}>{msg.sender_name}</div>
                          <div style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 4 }}>{timeAgo(msg.created_at)}</div>
                        </div>
                      </div>
                    );
                  })}
                  <div ref={bottomRef} />
                </div>

                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <input
                    value={messageText}
                    onChange={e => setMessageText(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && sendMessage()}
                    placeholder="Digite uma mensagem para a sala..."
                    style={{ flex: 1, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}
                  />
                  <button className="btn-admin btn-primary" onClick={sendMessage} disabled={sending || !messageText.trim()}>
                    {sending ? 'Enviando...' : 'Enviar'}
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'posts' && <FeedPage feedType={`sala_${selectedRoom.id}`} />}

            {activeTab === 'files' && (
              <div className="surface-card" style={{ padding: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>Arquivos da Sala</div>
                  <label className="btn-admin btn-primary" style={{ cursor: 'pointer' }}>
                    {uploading ? 'Enviando...' : '+ Adicionar Arquivo'}
                    <input type="file" hidden multiple onChange={uploadFiles} />
                  </label>
                </div>

                {files.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Nenhum arquivo salvo nessa sala.</div>}

                {files.map(f => (
                  <div key={f.id} className="file-item">
                    <div className="file-icon">📎</div>
                    <div className="file-meta">
                      <div className="file-name">{f.name}</div>
                      <div className="file-size">{formatBytes(f.size)} · {f.uploaded_by} · {new Date(f.created_at).toLocaleDateString('pt-BR')}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <a href={api.assetUrl(f.url)} target="_blank" rel="noopener noreferrer" download={f.name} className="btn-admin btn-secondary" style={{ textDecoration: 'none', padding: '5px 10px', fontSize: 12 }}>
                        ⬇ Baixar
                      </a>
                      <button className="btn-admin btn-danger" style={{ padding: '5px 8px', fontSize: 12 }} onClick={() => removeFile(f.id)}>
                        🗑
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'members' && (
              <div className="surface-card" style={{ padding: 14 }}>
                {canManageMembers && (
                  <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <select value={selectedMemberKey} onChange={e => setSelectedMemberKey(e.target.value)} style={{ flex: 1, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}>
                      <option value="">Selecionar colaborador...</option>
                      {availableUsers.map(u => <option key={u.key} value={u.key}>{u.name}</option>)}
                    </select>
                    <button className="btn-admin btn-primary" onClick={addMember} disabled={!selectedMemberKey}>+ Adicionar</button>
                  </div>
                )}

                {members.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Nenhum participante encontrado.</div>}

                <div style={{ display: 'grid', gap: 8 }}>
                  {members.map(m => (
                    <div key={m.user_key} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '8px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {userAvatar(m.photo_url, m.initials)}
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 700 }}>{m.name}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.role}</div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {m.user_key === selectedRoom.created_by && <span style={{ fontSize: 10, color: 'var(--gold)' }}>Criador</span>}
                        {canManageMembers && m.user_key !== selectedRoom.created_by && (
                          <button className="btn-admin btn-danger" style={{ padding: '3px 8px', fontSize: 11 }} onClick={() => removeMember(m.user_key)}>Remover</button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {showCall && (
        <div className="modal-overlay" onClick={() => setShowCall(false)}>
          <div className="modal-card" style={{ maxWidth: 980, padding: 10 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 15, fontWeight: 700 }}>Chamada de Voz · {selectedRoom?.name}</div>
              <button className="btn-admin btn-danger" onClick={() => setShowCall(false)}>Encerrar</button>
            </div>
            <iframe
              title="Voice Call"
              src={jitsiUrl}
              style={{ width: '100%', height: '70vh', border: '1px solid var(--border)', borderRadius: 10 }}
              allow="camera; microphone; fullscreen; display-capture; autoplay"
            />
          </div>
        </div>
      )}
    </div>
  );
}
