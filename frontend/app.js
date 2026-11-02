const fileInput = document.querySelector('#contract-image');
const fileName = document.querySelector('#file-name');
const preview = document.querySelector('#preview');
const status = document.querySelector('#status');
const maxFileSize = 10 * 1024 * 1024;
let previewUrl = null;

function showStatus(message, isError = false) {
  status.textContent = message;
  status.dataset.error = String(isError);
}

function clearPreview() {
  preview.hidden = true;
  preview.removeAttribute('src');
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
}

function checkFile() {
  clearPreview();
  const file = fileInput.files[0];
  fileName.textContent = file ? file.name : '선택한 파일 없음';
  if (!file) {
    showStatus('계약서 이미지를 선택해 주세요.');
    return;
  }
  if (!/\.(jpe?g|png)$/i.test(file.name) ||
      (file.type && !['image/jpeg', 'image/png'].includes(file.type))) {
    showStatus('JPG, JPEG, PNG 형식의 이미지만 선택할 수 있습니다.', true);
    return;
  }
  if (file.size > maxFileSize) {
    showStatus('파일 크기는 최대 10MiB까지 가능합니다.', true);
    return;
  }
  showStatus('이미지를 확인하고 있습니다.');
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
}

preview.addEventListener('load', () => {
  if (!previewUrl) return;
  preview.hidden = false;
  showStatus('이미지 파일을 확인했습니다.');
});
preview.addEventListener('error', () => {
  if (!previewUrl) return;
  clearPreview();
  showStatus('이미지를 읽을 수 없습니다. 다른 파일을 선택해 주세요.', true);
});
fileInput.addEventListener('change', checkFile);
document.querySelector('#file-form').addEventListener('submit', (event) => {
  event.preventDefault();
  checkFile();
});
window.addEventListener('pagehide', clearPreview);
