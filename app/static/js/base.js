document.addEventListener('DOMContentLoaded', () => {
  const body = document.body;
  const mobileSidebarToggle = document.querySelector('[data-mobile-sidebar-toggle]');
  const desktopSidebarToggle = document.querySelector('[data-desktop-sidebar-toggle]');
  const sidebarBackdrop = document.querySelector('[data-sidebar-backdrop]');
  const flashContainer = document.getElementById('flash-container');
  const navLinks = document.querySelectorAll('.nav-link-item, .logout-link');
  const tabTriggers = document.querySelectorAll('[data-bs-toggle="tab"], [data-bs-toggle="pill"]');

  const closeSidebar = () => {
    body.classList.remove('sidebar-open');
    if (mobileSidebarToggle) {
      mobileSidebarToggle.setAttribute('aria-expanded', 'false');
    }
  };

  const toggleMobileSidebar = () => {
    const isOpen = body.classList.toggle('sidebar-open');
    if (mobileSidebarToggle) {
      mobileSidebarToggle.setAttribute('aria-expanded', String(isOpen));
    }
  };

  const setCollapsedState = (collapsed) => {
    body.classList.toggle('sidebar-collapsed', collapsed);

    if (desktopSidebarToggle) {
      desktopSidebarToggle.setAttribute('aria-expanded', String(!collapsed));
      desktopSidebarToggle.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
      desktopSidebarToggle.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    }

    try {
      localStorage.setItem('waterDashboardSidebarCollapsed', collapsed ? '1' : '0');
    } catch (error) {
      /* Layout works even if localStorage is unavailable. */
    }
  };

  const restoreDesktopSidebarState = () => {
    try {
      const savedState = localStorage.getItem('waterDashboardSidebarCollapsed');
      if (savedState === '1' && window.innerWidth >= 992) {
        setCollapsedState(true);
      }
    } catch (error) {
      /* Ignore localStorage errors. */
    }
  };

  restoreDesktopSidebarState();

  if (mobileSidebarToggle) {
    mobileSidebarToggle.addEventListener('click', toggleMobileSidebar);
  }

  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', closeSidebar);
  }

  if (desktopSidebarToggle) {
    desktopSidebarToggle.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      setCollapsedState(!body.classList.contains('sidebar-collapsed'));
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeSidebar();
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth < 992) {
      closeSidebar();
    }
  });

  navLinks.forEach((link) => {
    try {
      const linkUrl = new URL(link.href, window.location.origin);
      const currentUrl = new URL(window.location.href);

      if (linkUrl.pathname === currentUrl.pathname) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
    } catch (error) {
      /* Ignore malformed URLs. */
    }

    link.addEventListener('click', () => {
      if (!link.classList.contains('logout-link')) {
        body.classList.add('is-navigating');
      }

      if (window.innerWidth < 992) {
        closeSidebar();
      }
    });
  });

  tabTriggers.forEach((trigger) => {
    trigger.addEventListener('shown.bs.tab', () => {
      const targetSelector = trigger.getAttribute('data-bs-target') || trigger.getAttribute('href');

      if (!targetSelector || !targetSelector.startsWith('#')) {
        return;
      }

      const targetPane = document.querySelector(targetSelector);

      if (!targetPane) {
        return;
      }

      targetPane.animate(
        [
          { opacity: 0.4, transform: 'translateY(8px)' },
          { opacity: 1, transform: 'translateY(0)' }
        ],
        {
          duration: 260,
          easing: 'ease-out'
        }
      );
    });
  });

  if (flashContainer && window.bootstrap) {
    window.setTimeout(() => {
      flashContainer.querySelectorAll('.alert').forEach((alert) => {
        const bootstrapAlert = window.bootstrap.Alert.getOrCreateInstance(alert);
        bootstrapAlert.close();
      });
    }, 5000);
  }
});