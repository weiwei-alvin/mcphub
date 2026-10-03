"""Bundled local schema registry. Unknown references never use network I/O."""
import json
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

def validator(directory, name):
    def refuse(uri): raise NoSuchResource(ref=uri)
    registry=Registry(retrieve=refuse)
    schemas={}
    for path in directory.glob('*.schema.json'):
        data=json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(data)
        schemas[path.name]=data
        registry=registry.with_resource(data.get('$id',path.name), Resource.from_contents(data))
    return Draft202012Validator(schemas[name],registry=registry)
