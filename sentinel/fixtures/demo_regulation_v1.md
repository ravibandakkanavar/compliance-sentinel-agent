# Demo Data Handling Regulation

This is a synthetic regulation written for demonstrating and testing Compliance
Sentinel. It is not law and does not reproduce the text of any real regulation.

## Section 1 - Storage of credentials

A service that stores user passwords shall store them only as salted hashes produced by an algorithm designed for password storage. A service shall not store, compare or transmit a user password in plain text.

Credentials that grant a service access to another system, including API keys, database passwords and signing keys, shall not be embedded in source code or in configuration files kept under version control.

## Section 2 - Personal data in logs

A service shall not write government identifiers, dates of birth or authentication secrets to application logs. Where an email address is needed in a log entry to investigate an incident, it shall be masked so that the full address cannot be recovered from the log alone.

## Section 3 - Data minimisation at collection

A service shall collect only the personal data that is necessary for the purpose stated to the user at the point of collection. A service shall not require a government identifier or income information as a condition of creating an account unless a law obliges the service to hold that information.

## Section 4 - Consent to marketing

Consent to receive marketing communications shall be given by a clear affirmative action of the user. A consent control that is selected by default does not constitute consent.

A service shall check the recorded consent of each recipient before sending a marketing communication, and shall not send marketing communications to a user who has not consented.

## Section 5 - Erasure on request

When a user asks for their account to be deleted, the service shall erase the personal data of that user from its primary data store without undue delay. Marking a record as deleted while retaining the personal data it contains does not satisfy this section.
