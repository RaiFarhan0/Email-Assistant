/**
 * Apple-Inspired Design System UI Helpers & Formatters
 */

(function(root) {
  const AppleUI = {
    /**
     * Formats ISO timestamp into concise, Apple-style relative or date string
     */
    formatDate(isoString) {
      if (!isoString) return "";
      try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return String(isoString);

        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / (1000 * 60));
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

        if (diffMins < 1) return "Just now";
        if (diffMins < 60) return `${diffMins}m`;
        if (diffHours < 24 && date.getDate() === now.getDate()) {
          return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        }
        if (diffDays === 1) return "Yesterday";
        if (diffDays < 7) {
          return date.toLocaleDateString([], { weekday: 'short' });
        }
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
      } catch (e) {
        return String(isoString || "");
      }
    },

    /**
     * Returns Apple-style priority dot metadata (red for urgent, amber for medium, grey for low)
     */
    getPriorityInfo(score) {
      const num = parseInt(score, 10);
      if (isNaN(num)) {
        return {
          dotClass: 'bg-[#8E8E93]',
          dotColor: '#8E8E93',
          label: 'Low',
          score: 0
        };
      }

      if (num >= 9) {
        // Urgent (9-10) -> Red dot
        return {
          dotClass: 'bg-[#FF453A]',
          dotColor: '#FF453A',
          label: 'Urgent',
          score: num
        };
      } else if (num >= 7) {
        // Medium priority (7-8) -> Amber dot
        return {
          dotClass: 'bg-[#FF9F0A]',
          dotColor: '#FF9F0A',
          label: 'Medium',
          score: num
        };
      } else {
        // Low priority (1-6) -> Subtle Grey dot
        return {
          dotClass: 'bg-[#8E8E93]',
          dotColor: '#8E8E93',
          label: 'Low',
          score: num
        };
      }
    },

    /**
     * Returns clean, capitalized category label
     */
    getCategoryLabel(category) {
      if (!category) return 'Business';
      const cat = String(category).toLowerCase();
      switch (cat) {
        case 'urgent': return 'Urgent';
        case 'meeting': return 'Meeting';
        case 'business': return 'Business';
        case 'newsletter': return 'Newsletter';
        case 'spam': return 'Spam';
        default: return cat.charAt(0).toUpperCase() + cat.slice(1);
      }
    },

    /**
     * Converts plain markdown text into restrained Apple-style HTML
     */
    markdownToHtml(text) {
      if (text === null || text === undefined) return "";
      try {
        let str = String(text);
        if (!str.trim()) return "";

        let html = str
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");

        // Bold
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>');
        // Italics
        html = html.replace(/\*(.*?)\*/g, '<em class="text-[#8E8E93]">$1</em>');
        // Inline code
        html = html.replace(/`(.*?)`/g, '<code class="bg-[#121212] text-white px-1.5 py-0.5 rounded text-xs font-mono">$1</code>');
        // Bullet points
        html = html.replace(/^\s*-\s+(.*)$/gm, '<li class="ml-4 list-disc text-white leading-relaxed">$1</li>');
        
        // Paragraphs
        const blocks = html.split(/\n\n+/).map(p => {
          const trimmed = p.trim();
          if (!trimmed) return "";
          if (trimmed.startsWith('<li')) return `<ul class="my-2 space-y-1.5">${trimmed}</ul>`;
          return `<p class="mb-2.5 last:mb-0 leading-relaxed text-white">${trimmed.replace(/\n/g, '<br/>')}</p>`;
        }).filter(Boolean);

        return blocks.join('') || html;
      } catch (e) {
        return String(text || "");
      }
    },

    /**
     * Extracts initials from name or email
     */
    getInitials(sender) {
      if (!sender) return "EM";
      const clean = String(sender).replace(/<.*?>/, '').trim();
      const parts = clean.split(/\s+/).filter(Boolean);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
      }
      return clean.substring(0, 2).toUpperCase() || "EM";
    }
  };

  // Expose globally
  root.AppleUI = AppleUI;
  root.GAIA = AppleUI;
})(typeof window !== 'undefined' ? window : this);
