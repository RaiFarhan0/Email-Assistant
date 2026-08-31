/**
 * Email Assistant - Alpine.js Application Store & Controller
 */

document.addEventListener('alpine:init', () => {
  Alpine.data('emailApp', () => ({
    // Application Navigation & Filters
    activeTab: 'inbox',
    sortOrder: 'chronological',
    categoryFilter: 'all',
    minPriorityFilter: null,
    searchQuery: '',
    expandedThreads: {},

    // Data State
    threads: [],
    selectedEmailId: null,
    selectedEmail: null,
    isLoadingEmails: false,
    isLoadingDetail: false,
    calendarEvents: [],
    isLoadingCalendarEvents: false,
    
    // Background Sync
    isSyncing: false,
    lastSyncedTime: null,
    lastSyncedTimestamp: null,
    lastSyncedRelative: 'Ready',
    syncIntervalId: null,
    syncTimeAgoIntervalId: null,

    // Onboarding & Settings
    isConfigured: true,
    showOnboarding: false,
    showSettingsModal: false,
    settingsForm: {
      email_address: '',
      app_password: '',
      imap_server: 'imap.gmail.com',
      smtp_server: 'smtp.gmail.com',
      imap_port: 993,
      smtp_port: 465,
      gemini_api_key: '',
      sync_interval_minutes: 5
    },
    mutedSenders: [],
    newMuteEmail: '',

    // Ghostwriter State
    ghostwriter: {
      tone: 'professional',
      content: '',
      isGenerating: false,
      isSending: false,
      isExpanded: true,
      currentDraftId: null
    },

    // Chat With Inbox (RAG-lite)
    chat: {
      query: '',
      isThinking: false,
      messages: [
        {
          role: 'assistant',
          text: 'Hello! I am your AI Inbox Assistant. Ask me anything about your emails, pending tasks, or upcoming meetings (English & Urdu supported).'
        }
      ]
    },

    // Toasts
    toasts: [],

    /**
     * Initialization routine
     */
    async init() {
      await this.loadSettings();
      await this.loadEmails();
      
      // Auto-poll every 30 seconds
      this.syncIntervalId = setInterval(() => {
        this.loadEmails(true);
      }, 30000);

      // Relative timestamp timer
      this.syncTimeAgoIntervalId = setInterval(() => {
        this.updateSyncTimeAgo();
      }, 10000);

      this.$nextTick(() => {
        if (window.lucide) {
          window.lucide.createIcons();
        }
      });
    },

    /**
     * Compute relative time for last sync
     */
    updateSyncTimeAgo() {
      if (!this.lastSyncedTimestamp) {
        this.lastSyncedRelative = this.lastSyncedTime ? `Synced ${this.lastSyncedTime}` : 'Ready';
        return;
      }
      const diffSec = Math.floor((Date.now() - this.lastSyncedTimestamp) / 1000);
      if (diffSec < 45) {
        this.lastSyncedRelative = 'Just now';
      } else if (diffSec < 90) {
        this.lastSyncedRelative = '1m ago';
      } else {
        const mins = Math.floor(diffSec / 60);
        this.lastSyncedRelative = `${mins}m ago`;
      }
    },

    /**
     * Formatting and UI helper methods
     */
    formatMarkdown(text) {
      if (window.AppleUI && typeof window.AppleUI.markdownToHtml === 'function') {
        return window.AppleUI.markdownToHtml(text);
      }
      return String(text || '');
    },

    formatDate(dateStr) {
      if (window.AppleUI && typeof window.AppleUI.formatDate === 'function') {
        return window.AppleUI.formatDate(dateStr);
      }
      return String(dateStr || '');
    },

    getPriorityInfo(score) {
      if (window.AppleUI && typeof window.AppleUI.getPriorityInfo === 'function') {
        return window.AppleUI.getPriorityInfo(score);
      }
      return { dotClass: 'bg-[#8E8E93]', dotColor: '#8E8E93', label: 'Low', score: 0 };
    },

    getCategoryLabel(category) {
      if (window.AppleUI && typeof window.AppleUI.getCategoryLabel === 'function') {
        return window.AppleUI.getCategoryLabel(category);
      }
      return String(category || 'Business');
    },

    getInitials(sender) {
      if (window.AppleUI && typeof window.AppleUI.getInitials === 'function') {
        return window.AppleUI.getInitials(sender);
      }
      return 'EM';
    },

    /**
     * Opens / expands Ghostwriter and focuses draft editor
     */
    openGhostwriter() {
      this.ghostwriter.isExpanded = true;
      this.$nextTick(() => {
        const ghostEl = document.getElementById('ghostwriter-section');
        if (ghostEl) {
          ghostEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
          const ta = ghostEl.querySelector('textarea');
          if (ta) ta.focus();
        }
        if (window.lucide) window.lucide.createIcons();
      });
    },

    /**
     * Helper to show a toast notification
     */
    toast(title, message = '', type = 'info') {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, title, message, type });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 4000);
    },

    /**
     * Load settings and check onboarding status
     */
    async loadSettings() {
      try {
        const res = await fetch('/settings');
        if (!res.ok) throw new Error('Failed to fetch settings');
        const data = await res.json();
        
        this.isConfigured = data.is_configured;
        this.mutedSenders = data.muted_senders || [];
        this.settingsForm.email_address = data.email_address || '';
        this.settingsForm.imap_server = data.imap_server || 'imap.gmail.com';
        this.settingsForm.smtp_server = data.smtp_server || 'smtp.gmail.com';
        this.settingsForm.imap_port = data.imap_port || 993;
        this.settingsForm.smtp_port = data.smtp_port || 465;
        this.settingsForm.sync_interval_minutes = data.sync_interval_minutes || 5;

        // Show onboarding wizard if missing essential credentials
        if (!this.isConfigured) {
          this.showOnboarding = true;
        }
      } catch (e) {
        console.error('Error loading settings:', e);
      }
    },

    /**
     * Save updated settings
     */
    async saveSettings(isOnboarding = false) {
      try {
        const res = await fetch('/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.settingsForm)
        });
        if (!res.ok) throw new Error('Failed to save settings');
        
        const data = await res.json();
        this.isConfigured = data.is_configured;
        
        if (isOnboarding) {
          this.showOnboarding = false;
          this.toast('Welcome to Email Assistant', 'Setup completed! Syncing your emails now...', 'success');
          await this.triggerSync();
        } else {
          this.showSettingsModal = false;
          this.toast('Settings Saved', 'Connection settings updated.', 'success');
        }
        await this.loadSettings();
      } catch (e) {
        this.toast('Error Saving Settings', e.message, 'error');
      }
    },

    /**
     * Fetch emails based on current filters
     */
    async loadEmails(isSilent = false) {
      if (!isSilent) this.isLoadingEmails = true;
      try {
        let url = `/emails?thread_grouped=true&sort=${encodeURIComponent(this.sortOrder || 'chronological')}`;
        if (this.categoryFilter && this.categoryFilter !== 'all') {
          url += `&category=${encodeURIComponent(this.categoryFilter)}`;
        }
        if (this.minPriorityFilter) {
          url += `&min_priority=${this.minPriorityFilter}`;
        }
        if (this.searchQuery.trim()) {
          url += `&search=${encodeURIComponent(this.searchQuery.trim())}`;
        }

        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to load emails');
        const data = await res.json();
        this.threads = data;

        // Automatically expand first thread if none expanded
        if (this.threads.length > 0 && Object.keys(this.expandedThreads).length === 0) {
          this.expandedThreads[this.threads[0].thread_id] = true;
          if (!this.selectedEmailId) {
            this.selectEmail(this.threads[0].emails[0].id);
          }
        }
      } catch (e) {
        console.error('Error loading emails:', e);
        if (!isSilent) this.toast('Error Loading Emails', e.message, 'error');
      } finally {
        if (!isSilent) this.isLoadingEmails = false;
        this.$nextTick(() => {
          if (window.lucide) window.lucide.createIcons();
        });
      }
    },

    /**
     * Set category filter
     */
    setCategoryFilter(category) {
      this.categoryFilter = category;
      this.loadEmails();
    },

    /**
     * Switch main navigation tab
     */
    setTab(tab) {
      this.activeTab = tab;
      if (tab === 'inbox') {
        this.sortOrder = 'chronological';
        this.categoryFilter = 'all';
        this.minPriorityFilter = null;
        this.loadEmails();
      } else if (tab === 'urgent') {
        this.sortOrder = 'priority';
        this.categoryFilter = 'all';
        this.minPriorityFilter = 7;
        this.loadEmails();
      } else if (tab === 'meetings') {
        this.loadCalendarEvents();
      } else if (tab === 'newsletters') {
        this.sortOrder = 'chronological';
        this.categoryFilter = 'newsletter';
        this.minPriorityFilter = null;
        this.loadEmails();
      }
      this.$nextTick(() => {
        if (window.lucide) window.lucide.createIcons();
      });
    },

    /**
     * Fetch all calendar events from backend
     */
    async loadCalendarEvents() {
      this.isLoadingCalendarEvents = true;
      try {
        const res = await fetch('/calendar-events');
        if (!res.ok) throw new Error('Failed to load calendar events');
        this.calendarEvents = await res.json();
      } catch (e) {
        console.error('Error loading calendar events:', e);
        this.toast('Error Loading Events', e.message, 'error');
      } finally {
        this.isLoadingCalendarEvents = false;
        this.$nextTick(() => {
          if (window.lucide) window.lucide.createIcons();
        });
      }
    },

    /**
     * Group calendar events into chronological buckets
     */
    getGroupedCalendarEvents() {
      if (!this.calendarEvents || this.calendarEvents.length === 0) return [];

      const now = new Date();
      const todayStr = now.toISOString().split('T')[0];

      const tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);
      const tomorrowStr = tomorrow.toISOString().split('T')[0];

      const nextWeek = new Date(now);
      nextWeek.setDate(nextWeek.getDate() + 7);
      const nextWeekStr = nextWeek.toISOString().split('T')[0];

      const groups = {
        today: { id: 'today', label: 'Today', badgeClass: 'text-white font-semibold', events: [] },
        tomorrow: { id: 'tomorrow', label: 'Tomorrow', badgeClass: 'text-white font-semibold', events: [] },
        thisWeek: { id: 'thisWeek', label: 'This Week', badgeClass: 'text-white font-semibold', events: [] },
        later: { id: 'later', label: 'Upcoming', badgeClass: 'text-white font-semibold', events: [] },
        past: { id: 'past', label: 'Past Events', badgeClass: 'text-[#8E8E93] font-normal', events: [] }
      };

      this.calendarEvents.forEach(ev => {
        const evDate = ev.date;
        if (!evDate) {
          groups.later.events.push(ev);
        } else if (evDate < todayStr) {
          groups.past.events.push(ev);
        } else if (evDate === todayStr) {
          groups.today.events.push(ev);
        } else if (evDate === tomorrowStr) {
          groups.tomorrow.events.push(ev);
        } else if (evDate <= nextWeekStr) {
          groups.thisWeek.events.push(ev);
        } else {
          groups.later.events.push(ev);
        }
      });

      return [
        groups.today,
        groups.tomorrow,
        groups.thisWeek,
        groups.later,
        groups.past
      ].filter(g => g.events.length > 0);
    },

    /**
     * Jump back to source email in inbox
     */
    async jumpToEmail(emailId) {
      if (!emailId) return;
      this.setTab('inbox');
      await this.selectEmail(emailId);
    },

    /**
     * Toggle thread expansion accordion
     */
    toggleThread(threadId) {
      this.expandedThreads[threadId] = !this.expandedThreads[threadId];
      this.$nextTick(() => {
        if (window.lucide) window.lucide.createIcons();
      });
    },

    /**
     * Select and view an email detail
     */
    async selectEmail(emailId) {
      this.selectedEmailId = emailId;
      this.isLoadingDetail = true;
      try {
        const res = await fetch(`/emails/${emailId}`);
        if (!res.ok) throw new Error('Failed to load email details');
        this.selectedEmail = await res.json();

        // Mark as read
        if (!this.selectedEmail.is_read) {
          await fetch(`/emails/${emailId}/read?is_read=true`, { method: 'PATCH' });
          this.selectedEmail.is_read = true;
          // Update in local thread list
          this.threads.forEach(th => {
            th.emails.forEach(em => {
              if (em.id === emailId) em.is_read = true;
            });
          });
        }

        // Reset ghostwriter
        this.ghostwriter.content = '';
        this.ghostwriter.currentDraftId = null;
        if (this.selectedEmail.drafts && this.selectedEmail.drafts.length > 0) {
          const latestDraft = this.selectedEmail.drafts[0];
          this.ghostwriter.content = latestDraft.content;
          this.ghostwriter.tone = latestDraft.tone;
          this.ghostwriter.currentDraftId = latestDraft.id;
        }
      } catch (e) {
        this.toast('Error Loading Email', e.message, 'error');
      } finally {
        this.isLoadingDetail = false;
        this.$nextTick(() => {
          if (window.lucide) window.lucide.createIcons();
        });
      }
    },

    /**
     * Trigger manual IMAP email sync
     */
    async triggerSync() {
      if (this.isSyncing) return;
      this.isSyncing = true;
      try {
        const res = await fetch('/emails/sync', { method: 'POST' });
        if (!res.ok) throw new Error('Sync failed');
        const data = await res.json();
        
        this.lastSyncedTimestamp = Date.now();
        this.lastSyncedTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        this.updateSyncTimeAgo();
        this.toast(
          'Sync Completed',
          `${data.emails_fetched} fetched, ${data.emails_classified} classified, ${data.meetings_created} calendar events created.`,
          'success'
        );
        await this.loadEmails(true);
        await this.loadCalendarEvents();
      } catch (e) {
        this.toast('Sync Failed', e.message, 'error');
      } finally {
        this.isSyncing = false;
      }
    },

    /**
     * Force re-classification of selected email
     */
    async forceReclassify() {
      if (!this.selectedEmailId) return;
      try {
        const res = await fetch(`/emails/${this.selectedEmailId}/classify`, { method: 'POST' });
        if (!res.ok) throw new Error('Re-classification failed');
        const data = await res.json();
        
        this.selectedEmail.category = data.category;
        this.selectedEmail.priority_score = data.priority_score;
        this.selectedEmail.summary = data.summary;
        this.toast('Triage Updated', `Category: ${data.category}, Priority: ${data.priority_score}/10`, 'success');
        await this.loadEmails(true);
      } catch (e) {
        this.toast('Error Classifying', e.message, 'error');
      }
    },

    /**
     * Add to calendar / generate .ics
     */
    async createCalendarEvent(targetEmailId = null) {
      const emailId = targetEmailId || this.selectedEmailId;
      if (!emailId) return;
      try {
        const res = await fetch(`/emails/${emailId}/create-event`, { method: 'POST' });
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Failed to extract calendar event');
        }
        const event = await res.json();
        
        if (this.selectedEmail && this.selectedEmail.id === emailId) {
          if (!this.selectedEmail.calendar_events) {
            this.selectedEmail.calendar_events = [];
          }
          this.selectedEmail.calendar_events.push(event);
        }
        await this.loadCalendarEvents();
        this.toast('Event Created', `Scheduled: ${event.title} on ${event.date}`, 'success');
        
        // Trigger download
        this.downloadIcs(event.id);
      } catch (e) {
        this.toast('Calendar Error', e.message, 'error');
      }
    },

    /**
     * Download .ics file
     */
    downloadIcs(eventId) {
      window.location.href = `/calendar-events/${eventId}/download`;
    },

    /**
     * Generate AI Ghostwriter Draft
     */
    async generateDraft(tone) {
      if (!this.selectedEmailId) return;
      this.ghostwriter.tone = tone || this.ghostwriter.tone;
      this.ghostwriter.isGenerating = true;
      try {
        const res = await fetch(`/emails/${this.selectedEmailId}/draft`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tone: this.ghostwriter.tone })
        });
        if (!res.ok) throw new Error('Failed to generate draft');
        const draft = await res.json();
        
        this.ghostwriter.content = draft.content;
        this.ghostwriter.currentDraftId = draft.id;
        this.toast('Draft Generated', `Tone: ${this.ghostwriter.tone}`, 'success');
      } catch (e) {
        this.toast('Draft Generation Failed', e.message, 'error');
      } finally {
        this.ghostwriter.isGenerating = false;
      }
    },

    /**
     * Send Ghostwriter Draft Reply
     */
    async sendReply() {
      if (!this.ghostwriter.currentDraftId) {
        this.toast('No Draft Available', 'Please generate or write a draft first.', 'error');
        return;
      }
      if (!this.ghostwriter.content.trim()) {
        this.toast('Empty Content', 'Cannot send an empty email reply.', 'error');
        return;
      }

      this.ghostwriter.isSending = true;
      try {
        const res = await fetch(`/drafts/${this.ghostwriter.currentDraftId}/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: this.ghostwriter.content })
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Failed to send reply');
        }
        const data = await res.json();
        this.toast('Reply Sent!', `Sent successfully to ${data.sent_to}`, 'success');
        this.ghostwriter.content = '';
        this.ghostwriter.currentDraftId = null;
      } catch (e) {
        this.toast('Send Failed', e.message, 'error');
      } finally {
        this.ghostwriter.isSending = false;
      }
    },

    /**
     * Send Natural Language Chat Query (RAG-lite & Compose New Email)
     */
    async sendChatQuery() {
      const q = this.chat.query.trim();
      if (!q || this.chat.isThinking) return;

      this.chat.messages.push({ role: 'user', text: q });
      this.chat.query = '';
      this.chat.isThinking = true;

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q })
        });
        if (!res.ok) throw new Error('Chat synthesis failed');
        const data = await res.json();

        let draftData = null;
        if (data.is_compose && data.draft) {
          draftData = {
            recipient: data.draft.recipient || '',
            subject: data.draft.subject || '',
            body: data.draft.body || '',
            tone: data.draft.tone || 'professional',
            isEditing: false,
            isSending: false,
            isSent: false,
            sentTo: null,
            editRecipient: data.draft.recipient || '',
            editSubject: data.draft.subject || '',
            editBody: data.draft.body || ''
          };
        }

        this.chat.messages.push({
          role: 'assistant',
          text: data.answer,
          referencedIds: data.referenced_email_ids,
          draft: draftData
        });
      } catch (e) {
        this.chat.messages.push({
          role: 'assistant',
          text: `Sorry, an error occurred while searching your inbox: ${e.message}`
        });
      } finally {
        this.chat.isThinking = false;
        this.$nextTick(() => {
          const chatBox = document.getElementById('chat-scroll-container');
          if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
          if (window.lucide) window.lucide.createIcons();
        });
      }
    },

    /**
     * Send email draft from Chat With Inbox upon explicit user confirmation
     */
    async sendChatDraft(draftObj) {
      if (!draftObj) return;
      const recipient = (draftObj.editRecipient || draftObj.recipient || '').trim();
      const subject = (draftObj.editSubject || draftObj.subject || '').trim();
      const body = (draftObj.editBody || draftObj.body || '').trim();

      if (!recipient || !recipient.includes('@')) {
        this.toast('Invalid Recipient', 'Please provide a valid recipient email address (e.g. name@example.com).', 'error');
        draftObj.isEditing = true;
        return;
      }

      if (!body) {
        this.toast('Empty Body', 'Email body cannot be empty.', 'error');
        draftObj.isEditing = true;
        return;
      }

      draftObj.isSending = true;
      try {
        const res = await fetch('/chat/send-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            to_email: recipient,
            subject: subject || 'No Subject',
            body: body
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Failed to send email');
        }

        const data = await res.json();
        draftObj.isSent = true;
        draftObj.sentTo = data.sent_to;
        draftObj.isEditing = false;
        draftObj.recipient = recipient;
        draftObj.subject = subject;
        draftObj.body = body;

        this.toast('Email Sent!', `Successfully dispatched to ${data.sent_to}`, 'success');
      } catch (e) {
        this.toast('Send Failed', e.message, 'error');
      } finally {
        draftObj.isSending = false;
        this.$nextTick(() => {
          if (window.lucide) window.lucide.createIcons();
        });
      }
    },

    /**
     * Toggle edit mode for chat draft
     */
    toggleEditChatDraft(draftObj) {
      if (!draftObj) return;
      draftObj.isEditing = !draftObj.isEditing;
      if (draftObj.isEditing) {
        draftObj.editRecipient = draftObj.editRecipient || draftObj.recipient || '';
        draftObj.editSubject = draftObj.editSubject || draftObj.subject || '';
        draftObj.editBody = draftObj.editBody || draftObj.body || '';
      }
      this.$nextTick(() => {
        if (window.lucide) window.lucide.createIcons();
      });
    },

    /**
     * Save draft edits back to view mode
     */
    saveChatDraftEdits(draftObj) {
      if (!draftObj) return;
      draftObj.recipient = (draftObj.editRecipient || '').trim();
      draftObj.subject = (draftObj.editSubject || '').trim();
      draftObj.body = (draftObj.editBody || '').trim();
      draftObj.isEditing = false;
      this.$nextTick(() => {
        if (window.lucide) window.lucide.createIcons();
      });
    },

    /**
     * Mute a sender email
     */
    async addMutedSender() {
      const email = this.newMuteEmail.trim().toLowerCase();
      if (!email || !email.includes('@')) {
        this.toast('Invalid Email', 'Please enter a valid email address to mute.', 'error');
        return;
      }

      try {
        const res = await fetch('/settings/mute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sender_email: email })
        });
        if (!res.ok) throw new Error('Failed to mute sender');
        this.newMuteEmail = '';
        this.toast('Sender Muted', `${email} will be ignored in future syncs.`, 'success');
        await this.loadSettings();
      } catch (e) {
        this.toast('Error Muting Sender', e.message, 'error');
      }
    },

    /**
     * Unmute a sender email
     */
    async removeMutedSender(senderEmail) {
      try {
        const res = await fetch(`/settings/mute/${encodeURIComponent(senderEmail)}`, {
          method: 'DELETE'
        });
        if (!res.ok) throw new Error('Failed to unmute sender');
        this.toast('Sender Unmuted', `${senderEmail} removed from muted list.`, 'success');
        await this.loadSettings();
      } catch (e) {
        this.toast('Error Unmuting', e.message, 'error');
      }
    }
  }));
});
