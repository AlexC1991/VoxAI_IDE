import re

class CodeParser:
    @staticmethod
    def extract_code(text):
        """
        Extracts the first code block found in the text.
        Returns (language, code) or (None, None) if no block found.
        """
        # Regex for ```language code ```
        # We capture language (optional) and content
        pattern = r"```(\w*)\n([\s\S]*?)```"
        match = re.search(pattern, text)
        
        if match:
            language = match.group(1).strip()
            code = match.group(2)
            return language, code
        
        return None, None
    
    @staticmethod
    def extract_filename(text):
        """
        Attempts to find a filename pattern like # filename: test.py or similar context.
        This is a heuristic.
        """
        # Look for headers or comments pointing to files
        # pattern = r"File: `?([\w\./-]+)`?"
        pass 
