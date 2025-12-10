import React from "react";
import "./ControlPanel.css";

interface ControlPanelProps {
  ready: boolean;
  onUploadPPT: (file: File) => void;
  isRecording: boolean;
}

export const ControlPanel: React.FC<ControlPanelProps> = ({
  ready,
  onUploadPPT,
  isRecording,
}) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      // Validate file type
      const validExtensions = [".ppt", ".pptx"];
      const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf("."));
      if (!validExtensions.includes(fileExtension)) {
        alert("Please upload a PowerPoint file (.ppt or .pptx)");
        return;
      }
      onUploadPPT(file);
    }
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const file = event.dataTransfer.files[0];
    if (file) {
      const validExtensions = [".ppt", ".pptx"];
      const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf("."));
      if (validExtensions.includes(fileExtension)) {
        onUploadPPT(file);
      }
    }
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  };

  return (
    <div className="control-panel">
      {!ready ? (
        <div 
          className="upload-section"
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          style={{
            border: "2px dashed #ccc",
            borderRadius: "8px",
            padding: "40px",
            textAlign: "center",
            cursor: "pointer",
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".ppt,.pptx"
            onChange={handleFileSelect}
            style={{ display: "none" }}
          />
          <p style={{ fontSize: "18px", marginBottom: "10px" }}>
            📁 Drop PowerPoint file here or click to select
          </p>
          <p style={{ fontSize: "14px", color: "#666" }}>
            Supports .ppt and .pptx files
          </p>
        </div>
      ) : (
        <div className="status-section">
          <div className="status-indicator">
            <span className={`status-dot ${ready ? "status-connected" : "status-disconnected"}`}></span>
            <span>{ready ? "🎤 Listening - Speak to interact" : "Disconnected"}</span>
          </div>
          {isRecording && (
            <p style={{ fontSize: "14px", color: "#666", marginTop: "10px" }}>
              Voice controls active - Say "next slide", "previous slide", or ask questions
            </p>
          )}
        </div>
      )}
    </div>
  );
};


