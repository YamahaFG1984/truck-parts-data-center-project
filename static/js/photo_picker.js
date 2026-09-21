/* Photo picker for the image inquiry page: click, drag-and-drop or paste.
 *
 * Pasting matters in practice — customers send screenshots over WeChat or email
 * and sales copy them straight out of the chat window. Whichever way the file
 * arrives it ends up in the real <input type="file">, so the form posts exactly
 * as it would without JavaScript; with JavaScript off the plain input still works.
 *
 * Registered through alpine:init because this file is deferred *after*
 * alpine.min.js: a plain global would not exist yet when Alpine evaluates x-data.
 */
document.addEventListener("alpine:init", () => {
  Alpine.data("photoPicker", () => ({
    ACCEPTED: ["image/jpeg", "image/png", "image/webp"],
    name: "",
    size: "",
    preview: "",
    error: "",
    dragging: false,

    init() {
      this.maxMb = Number(this.$el.dataset.maxMb || 10);
      // Paste anywhere on the page: nobody aims at a drop zone before Ctrl-V.
      this.onPaste = (event) => {
        const file = [...(event.clipboardData?.files || [])][0]
          || [...(event.clipboardData?.items || [])]
            .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
            .map((item) => item.getAsFile())[0];
        if (file) {
          event.preventDefault();
          this.take(file);
        }
      };
      document.addEventListener("paste", this.onPaste);
    },

    destroy() {
      document.removeEventListener("paste", this.onPaste);
      this.clearPreview();
    },

    drop(event) {
      this.dragging = false;
      const file = event.dataTransfer?.files?.[0];
      if (file) this.take(file);
    },

    pick(event) {
      const file = event.target.files?.[0];
      if (file) this.take(file, { alreadyInInput: true });
    },

    take(file, { alreadyInInput = false } = {}) {
      if (!this.ACCEPTED.includes(file.type)) {
        return this.reject("只支持 jpg、png 或 webp 图片。");
      }
      if (file.size > this.maxMb * 1024 * 1024) {
        return this.reject(`图片 ${this.human(file.size)}，超过 ${this.maxMb} MB 上限。`);
      }
      if (!alreadyInInput) {
        // The only cross-browser way to put a File into a file input.
        const box = new DataTransfer();
        box.items.add(file);
        this.$refs.input.files = box.files;
      }
      this.clearPreview();
      this.error = "";
      this.name = file.name || "clipboard.png";
      this.size = this.human(file.size);
      this.preview = URL.createObjectURL(file);
      this.$refs.submit.focus();
    },

    reject(message) {
      this.clear();
      this.error = message;
    },

    clear() {
      this.clearPreview();
      this.$refs.input.value = "";
      this.name = "";
      this.size = "";
      this.error = "";
    },

    clearPreview() {
      if (this.preview) URL.revokeObjectURL(this.preview);
      this.preview = "";
    },

    human(bytes) {
      const kb = bytes / 1024;
      return kb < 1024 ? `${Math.round(kb)} KB` : `${(kb / 1024).toFixed(1)} MB`;
    },
  }));
});
