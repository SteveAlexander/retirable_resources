# Retirable resources

A Python library for using Google Cloud Firestore to manage resources have a lifecycle: creation -> use -> retirement.

During "use", each resource can be used for different purposes by a set
of "owners". Each owner can retire their use of the resource independently
of other owners. When all owners have retired a resource, it is automatically
retired.

## Testing

Run the emulator with `firebase emulators:start --project foo`

Then run the tests with `python -m unittest`

## TODO

Script up running the emmulator, and passing its port to the test script

`emulators:exec *scriptpath*`

see <https://firebase.google.com/docs/emulator-suite/install_and_configure>
also useful: <https://firebase.google.com/docs/emulator-suite/connect_firestore#web>
