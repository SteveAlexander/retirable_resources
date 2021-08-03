# Retirable resources

A Python library for using Google Cloud Firestore to manage resources have a lifecycle: creation -> use -> retirement.

During "use", each resource can be used for different purposes by a set
of "owners". Each owner can retire their use of the resource independently
of other owners. When all owners have retired a resource, it is automatically
retired.

## Example

```python
>>> import retirable_resources
>>> from google.cloud.firestore import Client
>>> r = retirable_resources.RetirableResources('foo.bar', client=Client())
>>> r.add_resource('r1')
'ok'
>>> r.set_owners(['aa', 'bb'])
>>> r.dispose()
```
