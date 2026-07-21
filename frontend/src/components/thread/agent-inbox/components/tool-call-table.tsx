import { ToolCall } from "@langchain/core/messages/tool";
import { prettifyText, unknownToPrettyDate } from "../utils";

export function ToolCallTable({ toolCall }: { toolCall: ToolCall }) {
  return (
    <div className="max-w-full min-w-0 overflow-hidden rounded-lg border">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th
              className="bg-muted px-2 py-0 text-left text-sm"
              colSpan={2}
            >
              {prettifyText(toolCall.name)}
            </th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(toolCall.args).map(([key, value]) => {
            let valueStr = "";
            if (["string", "number"].includes(typeof value)) {
              valueStr = value.toString();
            }

            const date = unknownToPrettyDate(value);
            if (date) {
              valueStr = date;
            }

            try {
              valueStr = valueStr || JSON.stringify(value, null);
            } catch {
              // failed to stringify, just assign an empty string
              valueStr = "";
            }

            return (
              <tr
                key={key}
                className="border-t"
              >
                <td className="w-1/3 px-2 py-1 text-xs font-medium break-words">
                  {prettifyText(key)}
                </td>
                <td className="px-2 py-1 font-mono text-xs break-all">
                  {valueStr}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
