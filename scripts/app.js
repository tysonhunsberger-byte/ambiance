const moduleTemplates = new Map();

function removeModuleElement(modEl) {
  if (!modEl || !modEl.parentElement) return;
  const moduleId = modEl.getAttribute('data-module');
  const parentMods = modEl.closest('[data-mods]') || modEl.parentElement;
  modEl.remove();
  if (moduleId) {
    document.dispatchEvent(new CustomEvent('module:removed', {
      detail: { id: moduleId, container: parentMods }
    }));
  }
}

export function attachModuleClose(modEl) {
  if (!modEl) return;
  const header = modEl.querySelector('.mod-hdr') || modEl;
  let closeBtn = header.querySelector('.mod-close');
  if (!closeBtn) {
    closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'mod-close';
    closeBtn.setAttribute('aria-label', 'Remove module');
    closeBtn.innerHTML = '&times;';
    header.appendChild(closeBtn);
  }
  if (closeBtn.dataset.bound === 'true') return;
  closeBtn.dataset.bound = 'true';
  closeBtn.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    removeModuleElement(modEl);
  });
}

export function captureModuleTemplates(root) {
  const scope = root || document;
  moduleTemplates.clear();
  scope.querySelectorAll('[data-module-template]').forEach((template) => {
    const id = template.getAttribute('data-module-template');
    if (!id) return;
    const clone = template.content ? template.content.cloneNode(true) : template.cloneNode(true);
    const modEl = clone.firstElementChild || clone;
    attachModuleClose(modEl);
    moduleTemplates.set(id, modEl.innerHTML);
  });
  return moduleTemplates;
}

export function getModuleTemplate(id) {
  return moduleTemplates.get(id) || null;
}
