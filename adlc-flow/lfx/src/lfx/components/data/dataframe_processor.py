from typing import Any, Dict, Optional
import pandas as pd
from lfx.custom.custom_component.component import Component

class DataFrameProcessor(Component):
    """A component that processes pandas DataFrames with various operations."""
    display_name: str = 'DataFrame Processor'
    description: str = 'Process and transform Dataframe with various operations like filtering, soring, and aggregation'
    documentation: str ='https://docs.langflow.org/components-dataframe-processor'
    icon: str = "file-text"
    priority: int = 100
    name: str = "dataframe_processor"
    inputs = []
    outputs= []
    def test_output_method(self):
        return
