import assert from 'node:assert/strict';

export async function organizationChecks({page, record, screenshots, download, sha, filename, plaintext}) {
  const idle = () => page.waitForFunction(() => document.querySelector('#files-panel').getAttribute('aria-busy') === 'false');
  const section = async name => { await idle(); await page.locator(`[data-collection="${name}"]`).click(); };
  const folder = async name => {
    await page.locator('#new-folder-button').click(); await page.locator('#folder-name').fill(name);
    await page.locator('#folder-form button[type=submit]').click(); await page.locator('#folder-dialog').waitFor({state:'hidden'}); await idle();
  };
  const remove = async name => {
    await page.getByRole('button',{name:`Удалить ${name}`,exact:true}).click();
    await page.locator('#confirm-delete-button').click(); await page.locator('#delete-dialog').waitFor({state:'hidden'}); await idle();
  };
  await section('drive'); await folder('Проекты');
  await page.getByRole('button',{name:'Проекты',exact:true}).click(); await folder('Документы');
  await page.getByRole('button',{name:'Переименовать Документы',exact:true}).click();
  await page.locator('#folder-name').fill('Архив'); await page.locator('#folder-form button[type=submit]').click();
  await page.locator('#folder-dialog').waitFor({state:'hidden'}); await idle();
  await page.getByRole('button',{name:'Архив',exact:true}).click();
  await page.locator('#file-input').setInputFiles({name:'в папке.txt',mimeType:'text/plain',buffer:Buffer.from('folder content')});
  await page.getByRole('button',{name:'Скачать в папке.txt',exact:true}).waitFor(); await idle();
  assert.equal((await download(page,'в папке.txt')).toString(),'folder content'); await idle();
  await screenshots('folders');
  await section('drive');
  await page.getByRole('button',{name:`Переместить ${filename}`,exact:true}).click();
  await page.locator('#move-parent').selectOption({label:'Мой диск / Проекты / Архив'});
  await page.locator('#move-form button[type=submit]').click(); await page.locator('#move-dialog').waitFor({state:'hidden'}); await idle();
  await page.getByRole('button',{name:'В избранное Проекты',exact:true}).click(); await idle();
  await section('starred'); await page.getByRole('button',{name:'Проекты',exact:true}).waitFor();
  await page.getByRole('button',{name:'Проекты',exact:true}).click(); await page.getByRole('button',{name:'Архив',exact:true}).click();
  assert.equal(sha(await download(page,filename)),sha(plaintext)); await idle();
  await page.getByRole('button',{name:`В избранное ${filename}`,exact:true}).click(); await idle();
  await section('starred'); await page.getByRole('button',{name:`Скачать ${filename}`,exact:true}).waitFor();
  await screenshots('favorites');
  await section('drive');
  const before = await page.locator('#quota-meter').getAttribute('value');
  await remove('Проекты'); await section('starred');
  assert.equal(await page.locator('.file-row').count(),0);
  await section('trash'); assert.equal(await page.locator('#quota-meter').getAttribute('value'),before);
  await screenshots('trash');
  await page.getByRole('button',{name:'Восстановить Проекты',exact:true}).click(); await idle(); await section('drive');
  await page.getByRole('button',{name:'Проекты',exact:true}).click(); await page.getByRole('button',{name:'Архив',exact:true}).click();
  assert.equal(sha(await download(page,filename)),sha(plaintext)); await idle();
  await page.getByRole('button',{name:`Переместить ${filename}`,exact:true}).click(); await page.locator('#move-parent').selectOption('');
  await page.locator('#move-form button[type=submit]').click(); await page.locator('#move-dialog').waitFor({state:'hidden'}); await idle();
  await section('drive'); await remove('Проекты'); await section('trash');
  await page.getByRole('button',{name:'Удалить навсегда Проекты',exact:true}).click();
  await page.locator('#confirm-delete-button').click(); await page.locator('#delete-dialog').waitFor({state:'hidden'}); await idle();
  assert.equal(await page.locator('.file-row').count(),0); assert.ok(Number(await page.locator('#quota-meter').getAttribute('value')) < Number(before));
  await section('drive'); assert.equal(sha(await download(page,filename)),sha(plaintext)); await idle();
  record('folders: nested create, rename, upload/download, move, favorite, recursive trash/restore/purge and quota');
}
