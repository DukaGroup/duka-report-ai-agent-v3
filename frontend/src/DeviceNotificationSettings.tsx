import { useState } from "react";
import { Bell, BellOff, LoaderCircle } from "lucide-react";
import {
  disableDeviceNotifications,
  enableDeviceNotifications,
  supportsDeviceNotifications,
} from "./deviceNotifications";
import { ErrorNotice } from "./ErrorNotice";
import { SERVICE_UNAVAILABLE } from "./locale";

export function DeviceNotificationSettings({
  userId,
  enabled,
  onChange,
  technical = false,
}: {
  userId: string;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  technical?: boolean;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const supported = supportsDeviceNotifications();
  return (
    <section className="panel device-notification-settings">
      <h2>Njoftimet e pajisjes</h2>
      <p className="muted">
        Merrni një njoftim me tingull kur përgjigjja ose raporti është gati,
        edhe kur faqja është në sfond. Shtypeni njoftimin për të hapur bisedën.
      </p>
      <p className="muted">
        Njoftimi nuk shfaq përmbajtjen e bisedës. Kur aplikacioni është i
        mbyllur, tingulli ndjek cilësimet e pajisjes.
      </p>
      <div className="device-notification-actions">
        <button
          className="button outline"
          disabled={!supported || busy}
          onClick={() => {
            setBusy(true);
            setError("");
            const result = enabled
              ? disableDeviceNotifications(userId)
              : enableDeviceNotifications(userId);
            void result
              .then(onChange)
              .catch((e: Error) =>
                setError(
                  e instanceof DOMException
                    ? "Njoftimet nuk u aktivizuan. Kontrolloni lejet e shfletuesit dhe provoni përsëri. Në iPhone/iPad, hapeni aplikacionin nga ekrani kryesor."
                    : e.message,
                ),
              )
              .finally(() => setBusy(false));
          }}
        >
          {busy ? (
            <LoaderCircle size={18} className="spin" />
          ) : enabled ? (
            <BellOff size={18} />
          ) : (
            <Bell size={18} />
          )}
          {enabled ? "Çaktivizo njoftimet" : "Aktivizo njoftimet"}
        </button>
        <span role="status">
          {enabled ? "Të aktivizuara në këtë pajisje" : "Të çaktivizuara"}
        </span>
      </div>
      {!supported && (
        <p className="muted">
          Kërkohet HTTPS ose localhost. Në iPhone/iPad, shtojeni aplikacionin në
          ekranin kryesor dhe hapeni prej aty.
        </p>
      )}
      {error && (
        <ErrorNotice className="error-banner" onDismiss={() => setError("")}>
          {technical ? error : SERVICE_UNAVAILABLE}
        </ErrorNotice>
      )}
    </section>
  );
}
