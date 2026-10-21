import {
  KeyRound,
  Plus,
  RotateCcw,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserX,
} from "lucide-react";
import type { User } from "./types";
import { Select } from "./Select";
import { IconButton } from "./IconButton";

export function MembersPanel({
  actor,
  users,
  onAdd,
  onRole,
  onRestart,
  onAccess,
  onRecover,
  onToggle,
  onRemove,
}: {
  actor: User;
  users: User[];
  onAdd: () => void;
  onRole: (user: User, role: User["role"]) => void;
  onRestart: (user: User) => void;
  onAccess: (user: User) => void;
  onRecover: (user: User) => void;
  onToggle: (user: User) => void;
  onRemove: (user: User) => void;
}) {
  const isDev = actor.role === "devs";
  return (
    <section className="panel members-panel">
      <div className="panel-heading">
        <h3>Anëtarët e hapësirës</h3>
        <IconButton label="Shto anëtar" onClick={onAdd}>
          <Plus size={18} />
        </IconButton>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Anëtar</th>
              <th>Roli</th>
              <th>Gjendja</th>
              <th>Veprimet</th>
            </tr>
          </thead>
          <tbody>
            {users.map((member) => (
              <tr key={member.id}>
                <td>
                  <strong>{member.name}</strong>
                  <small>{member.email}</small>
                </td>
                <td>
                  <span className="member-cell-label">Roli</span>
                  {isDev ? (
                    <Select
                      aria-label={`Roli i ${member.name}`}
                      value={member.role}
                      disabled={member.id === actor.id}
                      onChange={(event) =>
                        onRole(member, event.target.value as User["role"])
                      }
                    >
                      <option value="devs">Devs</option>
                      <option value="president">President</option>
                      <option value="manager">Manager</option>
                    </Select>
                  ) : member.role === "devs" ? (
                    "Devs"
                  ) : member.role === "president" ? (
                    "President"
                  ) : (
                    "Manager"
                  )}
                </td>
                <td>
                  <span className="member-cell-label">Gjendja</span>
                  {member.active ? "Aktiv" : "Joaktiv"}
                </td>
                <td>
                  <span className="member-cell-label">Veprimet</span>
                  <div
                    className="action-group member-actions"
                    role="group"
                    aria-label={`Veprimet për ${member.name}`}
                  >
                    {isDev && (
                      <>
                        <IconButton
                          label={`Rinis lidhjen: ${member.name}`}
                          onClick={() => onRestart(member)}
                        >
                          <RotateCcw size={18} />
                        </IconButton>
                        <IconButton
                          label={`${member.role === "manager" ? "Menaxho qasjen" : "Qasje në të gjitha databazat dhe kompanitë"}: ${member.name}`}
                          onClick={() => onAccess(member)}
                        >
                          <ShieldCheck size={18} />
                        </IconButton>
                        <IconButton
                          label={`Rikupero llogarinë: ${member.name}`}
                          disabled={!member.active}
                          onClick={() => onRecover(member)}
                        >
                          <KeyRound size={18} />
                        </IconButton>
                        <IconButton
                          label={`${member.active ? "Çaktivizo" : "Aktivizo"} anëtarin: ${member.name}`}
                          disabled={member.id === actor.id}
                          onClick={() => onToggle(member)}
                        >
                          {member.active ? (
                            <UserX size={18} />
                          ) : (
                            <UserCheck size={18} />
                          )}
                        </IconButton>
                      </>
                    )}
                    {member.id !== actor.id &&
                      (isDev || member.role !== "devs") && (
                        <IconButton
                          danger
                          className="action-destructive"
                          label={`Fshi anëtarin: ${member.name}`}
                          onClick={() => onRemove(member)}
                        >
                          <Trash2 size={18} />
                        </IconButton>
                      )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
