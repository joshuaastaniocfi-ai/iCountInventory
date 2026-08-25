// Scanner-specific PWA functionality
class ScannerPWA {
    constructor() {
        this.deferredPrompt = null;
        this.installButton = null;
        this.isInstalled = false;
        this.installOverlay = null;
        this.installOverlayMsg = null;
        this.init();
    }

    init() {
        // Check if already installed
        this.checkInstallationStatus();
        
        // Listen for beforeinstallprompt event
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            this.deferredPrompt = e;
            this.showInstallPrompt();
        });

        // Listen for appinstalled event
        window.addEventListener('appinstalled', () => {
            this.isInstalled = true;
            this.hideInstallPrompt();
            if (this._installSafetyTimeout) {
                clearTimeout(this._installSafetyTimeout);
                this._installSafetyTimeout = null;
            }
            this.updateOverlay('Installed! Launching...');
            setTimeout(() => {
                try {
                    if (window.matchMedia('(display-mode: standalone)').matches) {
                        location.reload();
                    } else {
                        window.location.href = '/scanner/mobile-scanner';
                    }
                } catch (e) {
                    console.log('Auto-launch error:', e);
                } finally {
                    this.hideOverlay(300);
                }
            }, 600);
        });

        // Check if running in standalone mode
        if (window.matchMedia('(display-mode: standalone)').matches) {
            this.isInstalled = true;
            this.showInstalledMessage();
            this.setupNavigationGuard();
        }

        // Prepare overlay
        this.createInstallOverlay();
    }

    checkInstallationStatus() {
        if (window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches) {
            this.isInstalled = true;
        }
    }

    showInstallPrompt() {
        // Create install banner at the top of the scanner
        this.createInstallBanner();
    }

    hideInstallPrompt() {
        const banner = document.getElementById('pwa-install-banner');
        if (banner) banner.remove();
    }

    createInstallBanner() {
        // Check if banner already exists
        if (document.getElementById('pwa-install-banner')) {
            return;
        }

        // Create install banner (short and simple)
        const banner = document.createElement('div');
        banner.id = 'pwa-install-banner';
        banner.className = 'alert alert-info alert-dismissible fade show';
        banner.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1050;
            margin: 0;
            border-radius: 0;
            border: none;
            background: linear-gradient(135deg, #4a5da7, #667eea);
            color: white;
            text-align: center;
            padding: 10px 14px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        `;

        banner.innerHTML = `
            <div class="d-flex align-items-center justify-content-between">
                <div class="d-flex align-items-center">
                    <i class="fas fa-mobile-alt me-2"></i>
                    <span>Install app</span>
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-light btn-sm" onclick="window.scannerPWA.installApp()">
                        <i class="fas fa-download me-1"></i> Install
                    </button>
                    <button type="button" class="btn-close btn-close-white" onclick="window.scannerPWA.hideInstallPrompt()"></button>
                </div>
            </div>
        `;

        // Add to body
        document.body.appendChild(banner);

        // Adjust scanner wrapper position
        const scannerWrapper = document.querySelector('.scanner-wrapper');
        if (scannerWrapper) {
            scannerWrapper.style.marginTop = '80px';
        }
    }

    createInstallOverlay() {
        if (document.getElementById('pwa-install-overlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'pwa-install-overlay';
        overlay.style.cssText = `
            position: fixed; inset: 0; z-index: 1200; display: none;
            align-items: center; justify-content: center;
            background: rgba(255,255,255,0.9); backdrop-filter: blur(2px);
        `;
        const box = document.createElement('div');
        box.style.cssText = `
            background: #fff; border-radius: 10px; padding: 16px 20px;
            box-shadow: 0 6px 18px rgba(0,0,0,0.15); min-width: 220px;
            display: flex; align-items: center; gap: 10px;
        `;
        const spinner = document.createElement('i');
        spinner.className = 'fas fa-spinner fa-spin';
        spinner.style.fontSize = '18px';
        const msg = document.createElement('span');
        msg.textContent = 'Preparing...';
        msg.style.fontWeight = '600';
        box.appendChild(spinner);
        box.appendChild(msg);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
        this.installOverlay = overlay;
        this.installOverlayMsg = msg;
    }

    showOverlay(message = 'Installing...') {
        if (!this.installOverlay) this.createInstallOverlay();
        if (this.installOverlayMsg) this.installOverlayMsg.textContent = message;
        this.installOverlay.style.display = 'flex';
    }

    updateOverlay(message) {
        if (this.installOverlayMsg) this.installOverlayMsg.textContent = message;
    }

    hideOverlay(delayMs = 0) {
        if (!this.installOverlay) return;
        if (delayMs > 0) {
            setTimeout(() => { this.installOverlay.style.display = 'none'; }, delayMs);
        } else {
            this.installOverlay.style.display = 'none';
        }
    }

    async installApp() {
        if (!this.deferredPrompt) {
            console.log('Install prompt not available');
            return;
        }

        try {
            this.showOverlay('Installing app...');
            // Show the install prompt
            this.deferredPrompt.prompt();
            
            // Wait for user response
            const { outcome } = await this.deferredPrompt.userChoice;
            
            if (outcome === 'accepted') {
                console.log('User accepted the install prompt');
                // Keep overlay until appinstalled or safety timeout
                this._installSafetyTimeout = setTimeout(() => {
                    if (!this.isInstalled) {
                        this.updateOverlay('Finishing setup...');
                        this.hideOverlay(1500);
                    }
                }, 30000);
                this.hideInstallPrompt();
            } else {
                console.log('User dismissed the install prompt');
                this.updateOverlay('Install canceled');
                this.hideOverlay(1200);
            }
            
            // Clear the deferred prompt
            this.deferredPrompt = null;
            
        } catch (error) {
            console.error('Error during installation:', error);
            this.updateOverlay('Install failed');
            this.hideOverlay(1500);
        }
    }

    showInstalledMessage() {
        // Check if we've already shown this message in this session
        const hasShownStandaloneMsg = sessionStorage.getItem('hasShownScannerStandaloneMsg');
        
        // If we've already shown the message, don't show it again
        if (hasShownStandaloneMsg === 'true') {
            return;
        }
        
        // Mark as shown for this session
        sessionStorage.setItem('hasShownScannerStandaloneMsg', 'true');
        
        // Show success message
        const message = document.createElement('div');
        message.className = 'alert alert-success';
        message.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1050;
            max-width: 300px;
            animation: slideInRight 0.3s ease-out;
        `;
        message.innerHTML = `
            <i class="fas fa-check-circle me-2"></i>
            App installed! Running in standalone mode
        `;

        // Add animation styles
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInRight {
                from { transform: translateX(100px); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(message);

        // Remove after 5 seconds
        setTimeout(() => {
            if (message.parentNode) {
                message.parentNode.removeChild(message);
            }
        }, 5000);
    }

    setupNavigationGuard() {
        // Prevent navigation to external sites in PWA mode
        document.addEventListener('click', (e) => {
            const link = e.target.closest('a');
            if (link && link.href) {
                const url = new URL(link.href);
                const currentDomain = window.location.hostname;
                
                // If external link, open in new tab
                if (url.hostname !== currentDomain) {
                    e.preventDefault();
                    window.open(link.href, '_blank');
                }
            }
        });

        // Handle back button in PWA
        if ('navigation' in window) {
            window.navigation.addEventListener('navigate', (e) => {
                // Ensure navigation stays within app scope
                if (e.destination.url && !e.destination.url.includes(window.location.hostname)) {
                    e.preventDefault();
                    window.location.href = '/scanner/mobile-scanner';
                }
            });
        }

        // Add PWA-specific navigation controls
        this.addPWANavigationControls();
    }

    addPWANavigationControls() {
        // Create a navigation header for PWA mode
        const navHeader = document.createElement('div');
        navHeader.id = 'pwa-nav-header';
        navHeader.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1040;
            background: #4a5da7;
            color: white;
            padding: 8px 16px;
            text-align: center;
            font-size: 14px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        `;
        navHeader.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-mobile-alt me-2"></i>
                <span>iCount Inventory Scanner</span>
                <button class="btn btn-sm btn-outline-light ms-auto me-2" onclick="if(window.PageLoader){PageLoader.show();} location.reload();">
                    <i class="fas fa-rotate-right"></i>
                </button>
                <button class="btn btn-sm btn-outline-light" onclick="window.location.href='/scanner/mobile-scanner'">
                    <i class="fas fa-home"></i>
                </button>
            </div>
        `;

        // Insert after the install banner
        const installBanner = document.getElementById('pwa-install-banner');
        if (installBanner) {
            installBanner.parentNode.insertBefore(navHeader, installBanner.nextSibling);
        } else {
            document.body.insertBefore(navHeader, document.body.firstChild);
        }

        // Adjust scanner wrapper position for both headers
        const scannerWrapper = document.querySelector('.scanner-wrapper');
        if (scannerWrapper) {
            scannerWrapper.style.marginTop = '120px';
        }
    }
}

// Initialize Scanner PWA when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Check if service worker is supported
    if ('serviceWorker' in navigator) {
        // Register service worker
        navigator.serviceWorker.register('/static/sw.js')
            .then((registration) => {
                console.log('Scanner Service Worker registered:', registration);
                // No overlay on initial load; overlays only during explicit install flow
                // Keep registration without showing any loading/updating overlay here
            })
            .catch((error) => {
                console.log('Scanner Service Worker registration failed:', error);
            });
    }

    // Initialize Scanner  PWA
    window.scannerPWA = new ScannerPWA();
}); 

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ScannerPWA;
}
