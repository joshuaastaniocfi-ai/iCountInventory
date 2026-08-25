/**
 * Mobile Device Detection Utility
 * Provides functions to detect mobile devices and manage scanner access
 */

class MobileDetection {
    constructor() {
        this.isMobile = this.detectMobile();
        this.deviceInfo = null;
    }

    /**
     * Detect if the current device is mobile
     * @returns {boolean}
     */
    detectMobile() {
        const userAgent = navigator.userAgent || navigator.vendor || window.opera;
        
        // Check for mobile keywords
        const mobileKeywords = [
            'mobile', 'android', 'iphone', 'ipad', 'blackberry', 
            'windows phone', 'opera mini', 'mobile safari', 'mobile chrome'
        ];
        
        return mobileKeywords.some(keyword => 
            userAgent.toLowerCase().includes(keyword)
        );
    }

    /**
     * Get detailed device information from server
     * @returns {Promise<Object>}
     */
    async getDeviceInfo() {
        try {
            const response = await fetch('/api/device-check');
            this.deviceInfo = await response.json();
            return this.deviceInfo;
        } catch (error) {
            console.error('Error fetching device info:', error);
            return null;
        }
    }

    /**
     * Check if scanner is accessible for current user
     * @returns {Promise<Object>}
     */
    async checkScannerAccess() {
        try {
            const response = await fetch('/api/scanner-status');
            return await response.json();
        } catch (error) {
            console.error('Error checking scanner access:', error);
            return {
                success: false,
                message: 'Unable to check scanner access',
                code: 'NETWORK_ERROR'
            };
        }
    }

    /**
     * Show or hide scanner-related elements based on device compatibility
     */
    async updateScannerVisibility() {
        const scannerElements = document.querySelectorAll('[data-scanner-only]');
        
        if (scannerElements.length === 0) return;

        const accessCheck = await this.checkScannerAccess();
        
        scannerElements.forEach(element => {
            if (accessCheck.success) {
                element.style.display = '';
                element.classList.remove('d-none');
            } else {
                element.style.display = 'none';
                element.classList.add('d-none');
            }
        });

        // Update scanner links
        const scannerLinks = document.querySelectorAll('[data-scanner-link]');
        scannerLinks.forEach(link => {
            if (accessCheck.success) {
                link.href = accessCheck.scanner_url || '{{ url_for('scanner.mobile_scanner') }}';
                link.classList.remove('disabled');
                link.removeAttribute('title');
            } else {
                link.href = '#';
                link.classList.add('disabled');
                link.title = accessCheck.message;
            }
        });
    }

    /**
     * Add mobile-specific CSS classes to body
     */
    addMobileClasses() {
        if (this.isMobile) {
            document.body.classList.add('mobile-device');
            
            // Add device-specific classes
            if (this.deviceInfo) {
                document.body.classList.add(`device-${this.deviceInfo.device_type}`);
            }
        } else {
            document.body.classList.add('desktop-device');
        }
    }

    /**
     * Initialize mobile detection
     */
    async init() {
        await this.getDeviceInfo();
        this.addMobileClasses();
        await this.updateScannerVisibility();
        
        // Dispatch custom event when ready
        window.dispatchEvent(new CustomEvent('mobileDetectionReady', {
            detail: {
                isMobile: this.isMobile,
                deviceInfo: this.deviceInfo
            }
        }));
    }

    /**
     * Get mobile status
     * @returns {boolean}
     */
    getMobileStatus() {
        return this.isMobile;
    }

    /**
     * Get device info
     * @returns {Object|null}
     */
    getDeviceInfo() {
        return this.deviceInfo;
    }
}

// Create global instance
window.mobileDetection = new MobileDetection();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.mobileDetection.init();
    });
} else {
    window.mobileDetection.init();
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MobileDetection;
}
