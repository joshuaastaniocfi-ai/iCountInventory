// PWA Installation Handler
class PWAInstaller {
    constructor() {
        this.deferredPrompt = null;
        this.installButton = null;
        this.isInstalled = false;
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
            this.updateInstallStatus();
        });

        // Check if running in standalone mode
        if (window.matchMedia('(display-mode: standalone)').matches) {
            this.isInstalled = true;
            this.updateInstallStatus();
        }
    }

    checkInstallationStatus() {
        // Check if app is installed
        if (window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches) {
            this.isInstalled = true;
        }
    }

    showInstallPrompt() {
        // Create install button if it doesn't exist
        if (!this.installButton) {
            this.createInstallButton();
        }
        
        // Show the install button
        if (this.installButton) {
            this.installButton.style.display = 'block';
        }
    }

    hideInstallPrompt() {
        if (this.installButton) {
            this.installButton.style.display = 'none';
        }
    }

    createInstallButton() {
        // Check if button already exists
        if (document.getElementById('pwa-install-btn')) {
            this.installButton = document.getElementById('pwa-install-btn');
            return;
        }

        // Create install button
        this.installButton = document.createElement('button');
        this.installButton.id = 'pwa-install-btn';
        this.installButton.className = 'btn btn-primary btn-install-pwa';
        this.installButton.innerHTML = `
            <i class="fas fa-download me-2"></i>
            Install App
        `;
        
        // Style the button
        this.installButton.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            border-radius: 25px;
            padding: 12px 24px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            animation: slideInUp 0.3s ease-out;
        `;

        // Add click event
        this.installButton.addEventListener('click', () => {
            this.installApp();
        });

        // Add to body
        document.body.appendChild(this.installButton);

        // Add CSS animation
        this.addInstallButtonStyles();
    }

    addInstallButtonStyles() {
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInUp {
                from {
                    transform: translateY(100px);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }
            
            .btn-install-pwa:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(0,0,0,0.2);
                transition: all 0.3s ease;
            }
        `;
        document.head.appendChild(style);
    }

    async installApp() {
        if (!this.deferredPrompt) {
            console.log('Install prompt not available');
            return;
        }

        try {
            // Show the install prompt
            this.deferredPrompt.prompt();
            
            // Wait for user response
            const { outcome } = await this.deferredPrompt.userChoice;
            
            if (outcome === 'accepted') {
                console.log('User accepted the install prompt');
                this.hideInstallPrompt();
            } else {
                console.log('User dismissed the install prompt');
            }
            
            // Clear the deferred prompt
            this.deferredPrompt = null;
            
        } catch (error) {
            console.error('Error during installation:', error);
        }
    }

    updateInstallStatus() {
        // Update UI based on installation status
        if (this.isInstalled) {
            // Hide install button
            this.hideInstallPrompt();
            
            // Show installed indicator
            this.showInstalledIndicator();
        }
    }

    showInstalledIndicator() {
        // Check if we've already shown this message in this session
        const hasShownStandaloneMsg = sessionStorage.getItem('hasShownStandaloneMsg');
        
        // If we've already shown the message, don't show it again
        if (hasShownStandaloneMsg === 'true') {
            return;
        }
        
        // Mark as shown for this session
        sessionStorage.setItem('hasShownStandaloneMsg', 'true');
        
        // Create installed indicator
        const indicator = document.createElement('div');
        indicator.id = 'pwa-installed-indicator';
        indicator.className = 'alert alert-success';
        indicator.innerHTML = `
            <i class="fas fa-check-circle me-2"></i>
            App is installed and running in standalone mode
        `;
        indicator.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            max-width: 300px;
            animation: slideInRight 0.3s ease-out;
        `;

        // Add animation styles
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInRight {
                from {
                    transform: translateX(100px);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(indicator);

        // Remove after 5 seconds
        setTimeout(() => {
            if (indicator.parentNode) {
                indicator.parentNode.removeChild(indicator);
            }
        }, 5000);
    }
}

// Initialize PWA installer when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Check if service worker is supported
    if ('serviceWorker' in navigator) {
        // Register service worker
        navigator.serviceWorker.register('/static/sw.js')
            .then((registration) => {
                console.log('Service Worker registered successfully:', registration);
            })
            .catch((error) => {
                console.log('Service Worker registration failed:', error);
            });
    }

    // Initialize PWA installer
    window.pwaInstaller = new PWAInstaller();
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PWAInstaller;
}
