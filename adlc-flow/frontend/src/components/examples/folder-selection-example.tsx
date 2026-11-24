import { translateUi, useUiLocale } from "@/i18n/ui";
import { useState } from "react";
import InputFileComponent from "@/components/core/parameterRenderComponent/components/inputFileComponent";

type FolderSelectionData = {
  value?: string;
  file_path?: string;
};

/**
 * Example component demonstrating the folder selection functionality
 * in the InputFileComponent. This shows how to enable folder selection
 * which allows users to select entire folders and recursively process
 * all supported files within them.
 */
export default function FolderSelectionExample() {
  useUiLocale();
  const [value, setValue] = useState<string>("");
  const [filePath, setFilePath] = useState<string>("");

  const handleOnNewValue = (data: Partial<FolderSelectionData>) => {
    setValue(data.value ?? "");
    setFilePath(data.file_path ?? "");
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h2 className="text-2xl font-bold mb-4">
          {translateUi("Folder Selection Example")}
        </h2>
        <p className="text-muted-foreground mb-6">
          {translateUi(
            "This example demonstrates the folder selection feature in the File Component. Toggle between Files and Folder mode to see the difference:",
          )}
        </p>
        <ul className="list-disc list-inside text-sm text-muted-foreground mb-6 space-y-1">
          <li>
            <strong>{translateUi("Files mode:")}</strong>{" "}
            {translateUi("Select individual files (standard behavior)")}
          </li>
          <li>
            <strong>{translateUi("Folder mode:")}</strong>{" "}
            {translateUi(
              "Select entire folders and recursively process all supported files",
            )}
          </li>
          <li>
            {translateUi(
              "In folder mode, only files matching the specified types will be processed",
            )}
          </li>
          <li>
            {translateUi(
              "Supports common document formats: PDF, TXT, DOC, DOCX, MD, etc.",
            )}
          </li>
        </ul>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-2 block">
            {translateUi("File Component with Folder Selection")}
          </label>
          <InputFileComponent
            value={value}
            file_path={filePath}
            handleOnNewValue={handleOnNewValue}
            disabled={false}
            fileTypes={[
              "pdf",
              "txt",
              "doc",
              "docx",
              "md",
              "rtf",
              "csv",
              "json",
            ]}
            isList={true}
            tempFile={true}
            editNode={false}
            id="folder-example"
            allowFolderSelection={true}
          />
        </div>

        {(value || filePath) && (
          <div className="p-4 bg-muted rounded-lg">
            <h3 className="font-medium mb-2">
              {translateUi("Selected Files:")}
            </h3>
            <div className="space-y-1 text-sm">
              <div>
                <strong>{translateUi("Value:")}</strong> {value}
              </div>
              <div>
                <strong>{translateUi("File Path:")}</strong> {filePath}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t pt-6">
        <h3 className="font-medium mb-2">
          {translateUi("Usage Instructions:")}
        </h3>
        <ol className="list-decimal list-inside text-sm text-muted-foreground space-y-1">
          <li>{translateUi("Toggle the switch to enable Folder mode")}</li>
          <li>
            {translateUi("Click the upload area or drag a folder to select it")}
          </li>
          <li>
            {translateUi(
              "The component will recursively find all supported files in the folder",
            )}
          </li>
          <li>
            {translateUi(
              "Only files matching the specified fileTypes will be processed",
            )}
          </li>
          <li>
            {translateUi(
              "All selected files will be uploaded and their paths returned",
            )}
          </li>
        </ol>
      </div>
    </div>
  );
}
