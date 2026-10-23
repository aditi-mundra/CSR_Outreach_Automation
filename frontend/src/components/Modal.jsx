// size="wide" is for panels with a lot of content (contact discovery);
// the default stays the compact form dialog.
export default function Modal({ title, onClose, children, size = "default" }) {
  const width = size === "wide" ? "max-w-5xl" : "max-w-lg";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className={`flex max-h-[92vh] w-full ${width} flex-col rounded-xl bg-white p-6 shadow-xl`}>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="-mx-6 overflow-y-auto px-6">{children}</div>
      </div>
    </div>
  );
}
