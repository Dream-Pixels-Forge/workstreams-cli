/**
 * Dashboard Header Component
 * Derived from Stitch project design tokens
 * Confined to web/ directory
 */

class DashboardHeader extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    const title = this.getAttribute('title') || 'Dashboard';
    const status = this.getAttribute('status') || '';

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: 'Space Mono', monospace;
          color: var(--primary);
        }

        .header-content {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 24px;
          background: var(--surface-container);
          border-radius: var(--border-radius, 8px);
          border-bottom: 1px solid var(--outline);
        }

        .header-title {
          font-size: 1.5rem;
          margin: 0;
        }

        .status-indicator {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .status-dot {
          width: 8px;
          height: 8px;
          background: var(--primary);
          border-radius: 50%;
          animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      </style>

      <div class="header-content">
        <h1 class="header-title">${title}</h1>
        ${status ? `
          <div class="status-indicator">
            <div class="status-dot"></div>
            <span>${status}</span>
          </div>
        ` : ''}
      </div>
    `;
  }
}

// Define the custom element
customElements.define('dashboard-header', DashboardHeader);