(() => {
  const t = (key, variables = {}) => window.CloudNimbusI18n?.t(key, variables) || key;

  const updateDeviceClass = () => {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const touch = window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
    const phoneLandscape = touch && Math.min(width, height) <= 500 && Math.max(width, height) <= 1024;
    document.documentElement.dataset.deviceClass = width <= 720 || phoneLandscape ? 'mobile' : (touch && width <= 1024 ? 'tablet' : 'desktop');
  };
  updateDeviceClass();
  window.addEventListener('resize', updateDeviceClass, { passive: true });
  window.addEventListener('orientationchange', updateDeviceClass, { passive: true });

  const closeDropdowns = (except) => {
    document.querySelectorAll('.dropdown-panel:not([hidden])').forEach((panel) => {
      if (panel !== except) {
        panel.hidden = true;
        panel.closest('.dropdown')?.querySelector('[data-dropdown-trigger]')?.setAttribute('aria-expanded', 'false');
      }
    });
  };

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-dropdown-trigger]');
    if (trigger) {
      const panel = trigger.closest('.dropdown')?.querySelector('.dropdown-panel');
      if (!panel) return;
      const willOpen = panel.hidden;
      closeDropdowns(panel);
      panel.hidden = !willOpen;
      trigger.setAttribute('aria-expanded', String(willOpen));
      event.stopPropagation();
      return;
    }
    if (!event.target.closest('.dropdown-panel')) closeDropdowns();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeDropdowns();
      document.querySelectorAll('dialog[open]').forEach((dialog) => dialog.close());
    }
  });

  document.addEventListener('click', (event) => {
    const close = event.target.closest('[data-dialog-close]');
    if (close) close.closest('dialog')?.close();
  });

  document.querySelectorAll('[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const fileBrowser = document.querySelector('[data-file-browser]');
  const viewButtons = document.querySelectorAll('[data-view-mode]');
  if (fileBrowser && viewButtons.length) {
    const setView = (mode) => {
      const nextMode = mode === 'list' ? 'list' : 'grid';
      fileBrowser.dataset.view = nextMode;
      viewButtons.forEach((button) => {
        const selected = button.dataset.viewMode === nextMode;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', String(selected));
      });
    };
    setView(document.documentElement.dataset.defaultView || 'grid');
    viewButtons.forEach((button) => button.addEventListener('click', () => setView(button.dataset.viewMode)));
  }

  const uploadForm = document.querySelector('[data-upload-form]');
  if (uploadForm) {
    const input = uploadForm.querySelector('input[type=file]');
    const zone = uploadForm.querySelector('[data-drop-zone]');
    const list = uploadForm.querySelector('[data-selected-files]');
    const zoneTitle = uploadForm.querySelector('[data-drop-zone-title]');
    const submitButton = uploadForm.querySelector('button[type=submit]');
    let selectedFiles = [];
    const fileKey = (file) => `${file.name}:${file.size}:${file.lastModified}`;
    const syncInput = () => {
      try {
        const transfer = new DataTransfer();
        selectedFiles.forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
      } catch (_) { /* The async uploader uses selectedFiles directly. */ }
    };
    const formatSize = (bytes) => {
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
      return `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
    };
    const fileWord = (count) => {
      if (count % 10 === 1 && count % 100 !== 11) return 'файл';
      if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) return 'файла';
      return 'файлов';
    };
    const render = () => {
      list.textContent = '';
      const hasFiles = selectedFiles.length > 0;
      zone.classList.toggle('has-files', hasFiles);
      list.hidden = !hasFiles;
      submitButton.disabled = !hasFiles;
      zoneTitle.textContent = hasFiles ? 'Добавить ещё файлы' : 'Выберите файлы';
      if (!hasFiles) return;
      const summary = document.createElement('div');
      summary.className = 'selected-files-summary';
      const total = selectedFiles.reduce((sum, file) => sum + file.size, 0);
      summary.textContent = `${selectedFiles.length} ${fileWord(selectedFiles.length)} · ${formatSize(total)}`;
      list.append(summary);
      selectedFiles.forEach((file) => {
        const row = document.createElement('div');
        row.className = 'selected-file-row';
        const icon = document.createElement('span');
        icon.className = 'selected-file-icon';
        const iconGlyph = document.createElement('span');
        iconGlyph.className = 'adwaita-icon icon-storage';
        iconGlyph.setAttribute('aria-hidden', 'true');
        icon.append(iconGlyph);
        const copy = document.createElement('span');
        copy.className = 'selected-file-copy';
        const name = document.createElement('strong');
        name.textContent = file.name;
        const size = document.createElement('small');
        size.textContent = formatSize(file.size);
        copy.append(name, size);
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'selected-file-remove';
        remove.setAttribute('aria-label', `Убрать ${file.name}`);
        const removeIcon = document.createElement('span');
        removeIcon.className = 'adwaita-icon icon-close';
        removeIcon.setAttribute('aria-hidden', 'true');
        remove.append(removeIcon);
        remove.addEventListener('click', () => {
          selectedFiles = selectedFiles.filter((candidate) => fileKey(candidate) !== fileKey(file));
          syncInput();
          render();
        });
        row.append(icon, copy, remove);
        list.append(row);
      });
    };
    const addFiles = (files) => {
      const known = new Set(selectedFiles.map(fileKey));
      Array.from(files).forEach((file) => {
        const key = fileKey(file);
        if (!known.has(key)) {
          selectedFiles.push(file);
          known.add(key);
        }
      });
      syncInput();
      render();
    };
    input.addEventListener('change', () => addFiles(input.files));
    ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add('dragging');
    }));
    ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove('dragging');
    }));
    zone.addEventListener('drop', (event) => {
      addFiles(event.dataTransfer.files);
    });
    uploadForm.addEventListener('submit', async (event) => {
      if (!window.fetch || !selectedFiles.length) return;
      event.preventDefault();
      const progress = uploadForm.querySelector('[data-upload-progress]');
      const progressBar = progress.querySelector('span');
      const statusText = progress.querySelector('[data-upload-status]');
      const submit = submitButton;
      const csrf = uploadForm.querySelector('input[name=csrfmiddlewaretoken]').value;
      const folderId = uploadForm.querySelector('input[name=folder]')?.value || null;
      progress.hidden = false;
      submit.disabled = true;
      let uploadedBytes = 0;
      const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);
      const request = async (url, options = {}) => {
        const response = await fetch(url, {credentials: 'same-origin', ...options, headers: {'X-CSRFToken': csrf, ...(options.headers || {})}});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || 'upload_failed');
        return payload;
      };
      try {
        for (const file of selectedFiles) {
          statusText.textContent = `Подготовка: ${file.name}`;
          const session = await request('/api/uploads/initiate/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()},
            body: JSON.stringify({name: file.name, size: file.size, content_type: file.type || 'application/octet-stream', folder_id: folderId}),
          });
          try {
            const count = Math.ceil(file.size / session.chunk_size);
            for (let part = 0; part < count; part += 1) {
              const start = part * session.chunk_size;
              const blob = file.slice(start, Math.min(file.size, start + session.chunk_size));
              const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))).map((byte) => byte.toString(16).padStart(2, '0')).join('');
              statusText.textContent = `${file.name}: часть ${part + 1} из ${count}`;
              await request(`/api/uploads/${session.upload_id}/parts/${part}/`, {method: 'PUT', headers: {'Content-Type': 'application/octet-stream', 'X-Chunk-SHA256': hash}, body: blob});
              uploadedBytes += blob.size;
              progressBar.style.width = `${Math.min(100, uploadedBytes * 100 / totalBytes)}%`;
            }
            statusText.textContent = `Проверяем: ${file.name}`;
            await request(`/api/uploads/${session.upload_id}/complete/`, {method: 'POST'});
          } catch (error) {
            await request(`/api/uploads/${session.upload_id}/abort/`, {method: 'POST'}).catch(() => {});
            throw error;
          }
        }
        statusText.textContent = 'Готово';
        window.location.reload();
      } catch (error) {
        statusText.textContent = error.message === 'telegram_required' ? 'Подтвердите Telegram в настройках, чтобы загружать файлы.' : `Ошибка: ${error.message}`;
        submit.disabled = false;
      }
    });
    uploadForm.querySelectorAll('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => {
      selectedFiles = [];
      syncInput();
      render();
    }));
    render();
  }

  document.querySelectorAll('[data-upload-show], [data-create-menu-open]').forEach((button) => {
    button.addEventListener('click', () => {
      closeDropdowns();
      const uploadDialog = document.querySelector('#upload-dialog');
      const form = uploadDialog?.querySelector('[data-upload-form]');
      if (!uploadDialog || !form) return;
      uploadDialog.showModal();
      form.querySelector('input[type=file]')?.click();
    });
  });

  const folderDialog = document.querySelector('#folder-dialog');
  document.querySelectorAll('[data-folder-create-open]').forEach((button) => button.addEventListener('click', () => {
    closeDropdowns();
    folderDialog?.showModal();
    folderDialog?.querySelector('input[name=name]')?.focus();
  }));

  const dialog = document.querySelector('#rename-dialog');
  if (dialog) {
    const form = dialog.querySelector('[data-rename-form]');
    const input = dialog.querySelector('[data-rename-input]');
    document.querySelectorAll('[data-rename-trigger]').forEach((button) => {
      button.addEventListener('click', () => {
        form.action = button.dataset.kind === 'folder' ? `/folders/${button.dataset.itemId}/rename/` : `/files/${button.dataset.itemId}/rename/`;
        input.value = button.dataset.itemName;
        closeDropdowns();
        dialog.showModal();
        input.focus();
        input.select();
      });
    });
    dialog.querySelectorAll('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => dialog.close()));
  }

  const shareDialog = document.querySelector('#share-dialog');
  if (shareDialog) {
    let shareState = null;
    const csrf = document.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
    const status = shareDialog.querySelector('[data-share-status]');
    const generalSelect = shareDialog.querySelector('[data-general-access]');
    const copyButton = shareDialog.querySelector('[data-copy-link]');
    const passwordToggle = shareDialog.querySelector('[data-password-required]');
    const passwordField = shareDialog.querySelector('[data-password-field]');
    const settingsForm = shareDialog.querySelector('[data-link-settings-form]');
    const grantForm = shareDialog.querySelector('[data-share-grant-form]');

    const api = async (url, options = {}) => {
      const response = await fetch(url, {credentials: 'same-origin', ...options, headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'fetch', ...(options.headers || {})}});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const firstField = data.fields && Object.values(data.fields)[0];
        const message = Array.isArray(firstField) && firstField[0]?.message;
        throw new Error(message || data.error || 'Не удалось сохранить');
      }
      return data;
    };

    const renderShare = (data) => {
      shareState = data;
      shareDialog.querySelector('#share-title').textContent = t('share_title', {name: data.name});
      shareDialog.querySelector('[data-share-owner-avatar]').textContent = data.owner.username.slice(0, 1).toUpperCase();
      shareDialog.querySelector('[data-share-owner-name]').textContent = data.owner.username;
      shareDialog.querySelector('[data-share-owner-email]').textContent = data.owner.email;
      const grants = shareDialog.querySelector('[data-share-grants]');
      grants.textContent = '';
      data.grants.forEach((grant) => {
        const row = document.createElement('div');
        row.className = 'person-row';
        const avatar = document.createElement('span');
        avatar.className = 'avatar muted-avatar';
        avatar.textContent = (grant.username || grant.email).slice(0, 1).toUpperCase();
        const copy = document.createElement('span');
        copy.className = 'person-copy';
        const strong = document.createElement('strong');
        strong.textContent = grant.username || grant.email;
        const small = document.createElement('small');
        small.textContent = `${grant.email} · ${grant.role === 'editor' ? t('editor') : t('viewer')}`;
        copy.append(strong, small);
        const remove = document.createElement('button');
        remove.className = 'link-button';
        remove.type = 'button';
        remove.textContent = 'Убрать';
        remove.addEventListener('click', async () => {
          status.textContent = 'Удаляем доступ…';
          try { renderShare(await api(`/sharing/grants/${grant.id}/revoke/`, {method: 'POST'})); status.textContent = 'Доступ удалён'; }
          catch (error) { status.textContent = error.message; }
        });
        row.append(avatar, copy, remove);
        grants.append(row);
      });
      const passwordMode = data.general.mode === 'password';
      generalSelect.value = data.general.mode === 'restricted' ? 'restricted' : 'anyone';
      passwordToggle.checked = passwordMode;
      passwordField.hidden = !passwordMode;
      settingsForm.querySelector('input[name=expires_at]').value = data.general.expires_at || '';
      shareDialog.querySelector('[data-general-hint]').textContent = generalSelect.value === 'restricted' ? t('restricted_hint') : t('anyone_hint');
      copyButton.hidden = !data.general.url;
      copyButton.dataset.url = data.general.url || '';
      status.textContent = '';
    };

    document.querySelectorAll('[data-share-open]').forEach((button) => button.addEventListener('click', async () => {
      closeDropdowns();
      shareDialog.showModal();
      shareDialog.querySelector('#share-title').textContent = t('share_title', {name: button.dataset.itemName});
      status.textContent = 'Загружаем настройки…';
      try { renderShare(await api(`/sharing/api/${button.dataset.kind}/${button.dataset.itemId}/`)); }
      catch (error) { status.textContent = error.message; }
    }));

    generalSelect.addEventListener('change', async () => {
      if (!shareState) return;
      if (shareState.kind === 'folder' && generalSelect.value === 'anyone' && !window.confirm('Ссылка откроет эту папку и всё её содержимое. Продолжить?')) {
        generalSelect.value = 'restricted';
        return;
      }
      const body = new FormData();
      body.set('access_mode', generalSelect.value);
      body.set('expires_at', '');
      if (generalSelect.value === 'restricted') body.set('invalidate_existing', 'on');
      status.textContent = 'Сохраняем…';
      try { renderShare(await api(`/sharing/api/${shareState.kind}/${shareState.id}/general/`, {method: 'POST', body})); status.textContent = 'Сохранено'; }
      catch (error) { status.textContent = error.message; }
    });

    passwordToggle.addEventListener('change', () => { passwordField.hidden = !passwordToggle.checked; });
    settingsForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!shareState) return;
      const body = new FormData(settingsForm);
      body.set('access_mode', generalSelect.value === 'restricted' ? 'restricted' : (passwordToggle.checked ? 'password' : 'anyone'));
      status.textContent = 'Сохраняем…';
      try { renderShare(await api(`/sharing/api/${shareState.kind}/${shareState.id}/general/`, {method: 'POST', body})); status.textContent = 'Сохранено'; }
      catch (error) { status.textContent = error.message; }
    });

    grantForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!shareState) return;
      status.textContent = 'Добавляем…';
      try { renderShare(await api(`/sharing/api/${shareState.kind}/${shareState.id}/grants/`, {method: 'POST', body: new FormData(grantForm)})); grantForm.reset(); status.textContent = 'Доступ добавлен'; }
      catch (error) { status.textContent = error.message; }
    });

    copyButton.addEventListener('click', async () => {
      if (!copyButton.dataset.url) return;
      await navigator.clipboard.writeText(copyButton.dataset.url);
      status.textContent = 'Ссылка скопирована';
    });
  }

  const telegramForm = document.querySelector('[data-telegram-link-form]');
  if (telegramForm) {
    telegramForm.addEventListener('submit', () => {
      const card = telegramForm.closest('[data-telegram-card]');
      const waiting = telegramForm.querySelector('[data-telegram-wait]');
      const initialId = card.dataset.telegramId || '';
      const initialLinkedAt = card.dataset.linkedAt || '';
      waiting.hidden = false;
      let attempts = 0;
      const poll = async () => {
        attempts += 1;
        try {
          const response = await fetch(telegramForm.dataset.statusUrl, {credentials: 'same-origin'});
          const data = await response.json();
          if (data.linked && (data.telegram_user_id !== initialId || data.linked_at !== initialLinkedAt)) {
            waiting.textContent = 'Telegram подтверждён. Обновляем…';
            window.location.reload();
            return;
          }
        } catch (_) { /* A later poll can recover from a transient failure. */ }
        if (attempts < 100) window.setTimeout(poll, 3000);
        else waiting.textContent = 'Подтверждение не получено. Создайте новую ссылку и попробуйте ещё раз.';
      };
      window.setTimeout(poll, 1200);
    });
  }

  window.setTimeout(() => document.querySelectorAll('.toast').forEach((toast) => toast.remove()), 5000);
})();
