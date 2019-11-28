"""Utility functions for Model Pipeline Testing."""


class DataRetriever:

    def _get_data(self, data_content, content_type, source, data):
        if content_type in ['string', 'opfields']:
            return data_content.get(source)
        elif content_type == 'xpath':
            namespace = data_content.get('namespace')
            if isinstance(namespace, dict):
                # Already retrieved this from data reference
                return data_content
            else:
                # Get the reference namespace from data
                namespace = data.get(namespace)
            data_content['namespace'] = namespace.get('content')
            return data_content
        elif content_type == 'reference':
            return self.get_reference_data(
                data_content,
                data_content.get(source),
                source
            )
        elif content_type == 'file':
            return self.get_file_data(
                data_content.get('filename'),
                source
            )

    @classmethod
    def get_content_data(cls, action, data):
        content_idx = action.get('content', {})
        if not content_idx:
            return []
        content = data.get(content_idx)
        if not content:
            # no expected content data
            return content
        if isinstance(content, dict):
            content_type = content.get('type', 'string')
        else:
            return content
        return cls._get_data(cls, content, content_type, 'content', data)

    @classmethod
    def get_returns_data(cls, action, data):
        content_idx = action.get('returns', {})
        if not content_idx:
            return []
        content = data.get(content_idx)
        if not content:
            # no expected return data
            return content
        if isinstance(content, dict):
            content_type = content.get('type', 'string')
        else:
            return content
        return cls._get_data(cls, content, content_type, 'returns', data)

    @classmethod
    def get_reference_data(cls, ref, data, source):
        ref_data = data.get(ref)
        ref_type = ref_data.get('type')
        if ref_type == 'reference':
            return cls.get_reference_data(cls, ref_data.get(source), source)
        else:
            return cls._get_data(cls, ref_data, ref_type, source)

    @classmethod
    def get_file_data(cls, filename, source):
        # TODO: add this handling
        return ''

    @classmethod
    def get_data(cls, action, data):
        return (
            cls.get_content_data(action, data),
            cls.get_returns_data(action, data)
        )
