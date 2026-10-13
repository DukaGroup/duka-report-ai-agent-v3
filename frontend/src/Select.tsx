import {
  Children,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { ReactNode, KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import {
  autoUpdate,
  flip,
  hide,
  offset,
  shift,
  size,
  useFloating,
} from "@floating-ui/react-dom";

type Option = { value: string; label: ReactNode; disabled?: boolean };
type Props = {
  children?: ReactNode;
  options?: Option[];
  name?: string;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  required?: boolean;
  allowCustom?: boolean;
  "aria-label"?: string;
  onChange?: (event: { target: { value: string } }) => void;
};

const names: Record<string, string> = {
  template_id: "Modeli i raportit",
  dataset_id: "Dataset-i",
  role: "Roli",
  kind: "Lloji i databazës",
  source_id: "Burimi",
  query_key: "Çelësi i pyetjes së miratuar",
};
function plain(node: ReactNode): string {
  return Children.toArray(node)
    .map((c) =>
      isValidElement<{ children?: ReactNode }>(c)
        ? plain(c.props.children)
        : String(c),
    )
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

export function Select(props: Props) {
  const options =
    props.options ||
    Children.toArray(props.children).flatMap((child) =>
      isValidElement<{
        value: string;
        children?: ReactNode;
        disabled?: boolean;
      }>(child)
        ? [
            {
              value: String(child.props.value),
              label: child.props.children,
              disabled: child.props.disabled,
            },
          ]
        : [],
    );
  const [selected, setSelected] = useState<string | undefined>();
  const value =
    props.value ?? selected ?? props.defaultValue ?? options[0]?.value ?? "";
  const [open, setOpen] = useState(false),
    [active, setActive] = useState(0),
    [search, setSearch] = useState("");
  const trigger = useRef<HTMLButtonElement>(null),
    menu = useRef<HTMLDivElement>(null);
  const id = useId(),
    typed = useRef(""),
    typedAt = useRef(0);
  const items = props.allowCustom
    ? options.filter(
        (o) =>
          plain(o.label).toLowerCase().includes(search.toLowerCase()) ||
          o.value.toLowerCase().includes(search.toLowerCase()),
      )
    : options;
  const current = options.find((o) => o.value === value);
  const { refs, floatingStyles, isPositioned, middlewareData } = useFloating({
    open,
    placement: "bottom-start",
    strategy: "fixed",
    transform: false,
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(6),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
      size({
        padding: 8,
        apply({ availableHeight, availableWidth, rects, elements }) {
          Object.assign(elements.floating.style, {
            width: `${Math.min(Math.max(rects.reference.width, 220), Math.max(0, availableWidth))}px`,
            maxHeight: `${Math.max(0, Math.min(300, availableHeight))}px`,
          });
        },
      }),
      hide(),
    ],
  });
  useEffect(() => {
    if (open && middlewareData.hide?.referenceHidden) setOpen(false);
  }, [open, middlewareData.hide?.referenceHidden]);
  function choose(next: string) {
    setSelected(next);
    props.onChange?.({ target: { value: next } });
    setOpen(false);
    setSearch("");
    trigger.current?.focus();
  }
  function show() {
    if (props.disabled) return;
    setSearch("");
    setActive(
      Math.max(
        0,
        options.findIndex((o) => o.value === value),
      ),
    );
    setOpen(true);
  }
  useEffect(() => {
    if (props.disabled) setOpen(false);
  }, [props.disabled]);
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target))
        setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);
  useEffect(() => {
    const panel = menu.current;
    const option = panel?.querySelector<HTMLElement>(
      `[data-index="${active}"]`,
    );
    if (!panel || !option || !isPositioned) return;
    const bottom = option.offsetTop + option.offsetHeight;
    if (option.offsetTop < panel.scrollTop) panel.scrollTop = option.offsetTop;
    else if (bottom > panel.scrollTop + panel.clientHeight)
      panel.scrollTop = bottom - panel.clientHeight;
  }, [active, isPositioned]);
  useEffect(() => {
    if (open && isPositioned && props.allowCustom)
      menu.current
        ?.querySelector<HTMLInputElement>("input")
        ?.focus({ preventScroll: true });
  }, [open, isPositioned, props.allowCustom]);
  function keyboard(e: KeyboardEvent) {
    if (e.key === "Tab") {
      setOpen(false);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(e.key)) {
      if (
        props.allowCustom &&
        e.target instanceof HTMLInputElement &&
        e.key === " "
      )
        return;
      e.preventDefault();
      if (!open) {
        show();
        return;
      }
      if (e.key === "Enter" || e.key === " ") {
        if (items[active] && !items[active].disabled)
          choose(items[active].value);
        else if (props.allowCustom && search.trim()) choose(search.trim());
        return;
      }
      let next =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? items.length - 1
            : (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) %
              items.length;
      for (
        let tries = 0;
        tries < items.length && items[next]?.disabled;
        tries++
      )
        next =
          (next + (e.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
      setActive(next);
    } else if (
      e.key.length === 1 &&
      !props.allowCustom &&
      !e.ctrlKey &&
      !e.metaKey
    ) {
      typed.current =
        Date.now() - typedAt.current > 700 ? e.key : typed.current + e.key;
      typedAt.current = Date.now();
      const index = options.findIndex(
        (o) =>
          !o.disabled &&
          plain(o.label).toLowerCase().startsWith(typed.current.toLowerCase()),
      );
      if (index >= 0) {
        if (open) setActive(index);
        else choose(options[index].value);
      }
    }
  }
  return (
    <span className="custom-select">
      {props.name && (
        <input
          type="hidden"
          name={props.name}
          value={value}
          disabled={props.disabled}
        />
      )}
      <button
        ref={(node) => {
          trigger.current = node;
          refs.setReference(node);
        }}
        type="button"
        className="select-trigger"
        role="combobox"
        aria-label={
          props["aria-label"] || names[props.name || ""] || "Zgjidhni"
        }
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup="listbox"
        aria-required={props.required}
        aria-activedescendant={
          open && items[active] ? `${id}-${active}` : undefined
        }
        disabled={props.disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={keyboard}
      >
        <span className="select-value">
          {current?.label || value || "Zgjidhni…"}
        </span>
        <ChevronDown
          size={15}
          className={open ? "select-chevron open" : "select-chevron"}
        />
      </button>
      {open &&
        createPortal(
          <div
            ref={(node) => {
              menu.current = node;
              refs.setFloating(node);
            }}
            className="select-popover"
            style={{
              ...floatingStyles,
              visibility: isPositioned ? "visible" : "hidden",
            }}
            onKeyDown={keyboard}
          >
            {props.allowCustom && (
              <input
                aria-label="Kërko ose shkruaj një çelës"
                className="select-search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setActive(0);
                }}
              />
            )}
            <div
              role="listbox"
              id={id}
              aria-label={
                props["aria-label"] || names[props.name || ""] || "Zgjidhni"
              }
            >
              {items.map((option, index) => (
                <button
                  type="button"
                  role="option"
                  id={`${id}-${index}`}
                  data-index={index}
                  tabIndex={-1}
                  key={option.value}
                  aria-selected={option.value === value}
                  disabled={option.disabled}
                  className={`select-option ${index === active ? "active" : ""} ${option.value === value ? "selected" : ""}`}
                  onPointerMove={() => setActive(index)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(option.value)}
                >
                  <span>{option.label}</span>
                  {option.value === value && <Check size={15} />}
                </button>
              ))}
            </div>
            {props.allowCustom &&
              search.trim() &&
              !options.some((o) => o.value === search.trim()) && (
                <button
                  type="button"
                  className="select-option"
                  onClick={() => choose(search.trim())}
                >
                  Përdor: {search.trim()}
                </button>
              )}
            {!items.length && !search && (
              <div className="select-empty">
                Nuk ka zgjedhje të disponueshme.
              </div>
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
