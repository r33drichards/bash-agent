import React, { useState } from 'react';
import { AlertTriangle, Check, X } from 'lucide-react';
import type { ToolConfirmationData, ToolConfirmData } from '../types';

interface ToolConfirmationProps {
  confirmation: ToolConfirmationData;
  onConfirm: (data: ToolConfirmData) => void;
}

export const ToolConfirmation: React.FC<ToolConfirmationProps> = ({
  confirmation,
  onConfirm,
}) => {
  const [showRejectionInput, setShowRejectionInput] = useState(false);
  const [rejectionReason, setRejectionReason] = useState('');

  const handleConfirm = () => {
    onConfirm({
      tool_call_id: confirmation.tool_call_id,
      confirmed: true,
      tool_call: confirmation.tool_call,
    });
  };

  const handleReject = () => {
    if (showRejectionInput) {
      onConfirm({
        tool_call_id: confirmation.tool_call_id,
        confirmed: false,
        tool_call: confirmation.tool_call,
        rejection_reason: rejectionReason.trim(),
      });
    } else {
      setShowRejectionInput(true);
    }
  };

  const handleBack = () => {
    setShowRejectionInput(false);
    setRejectionReason('');
  };

  return (
    <div className="bg-surface border border-danger rounded-lg p-4 mb-4">
      <div className="flex items-center gap-2 text-danger font-semibold mb-3">
        <AlertTriangle className="w-4 h-4" />
        Tool Execution Required
      </div>
      
      <div className="text-text text-sm mb-3 space-y-2">
        <div>
          <strong>Tool:</strong> {confirmation.tool_name}
        </div>
        <div>
          <strong>Input:</strong>
          <pre className="bg-background border border-border rounded p-2 mt-1 text-xs overflow-x-auto">
            {JSON.stringify(confirmation.tool_input, null, 2)}
          </pre>
        </div>
      </div>
      
      {!showRejectionInput ? (
        <div className="flex gap-2">
          <button
            onClick={handleConfirm}
            className="bg-secondary hover:bg-secondary/80 text-background px-4 py-2 text-sm font-semibold rounded-md transition-colors flex items-center gap-2"
          >
            <Check className="w-3 h-3" />
            Execute
          </button>
          <button
            onClick={handleReject}
            className="bg-danger hover:bg-danger-hover text-white px-4 py-2 text-sm font-semibold rounded-md transition-colors flex items-center gap-2"
          >
            <X className="w-3 h-3" />
            Cancel
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div>
            <label className="block text-text text-sm mb-2">
              Reason for rejection (optional):
            </label>
            <input
              type="text"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="e.g., Command is too risky, need more context..."
              className="w-full bg-background border border-border text-text px-3 py-2 text-sm rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              autoFocus
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleReject}
              className="bg-danger hover:bg-danger-hover text-white px-4 py-2 text-sm font-semibold rounded-md transition-colors"
            >
              Submit Rejection
            </button>
            <button
              onClick={handleBack}
              className="bg-border hover:bg-border-hover text-text px-4 py-2 text-sm font-semibold rounded-md transition-colors"
            >
              Back
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
