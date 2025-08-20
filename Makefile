run:
	export MODE=live; \
	export CALENDAR_ID=43363a9f06275a2a761d2102ff2e610de594aae556d8cb677536d2f873e5a8f8@group.calendar.google.com; \
	python main.py

dry-run:
	export MODE=dry; \
	export CALENDAR_ID=43363a9f06275a2a761d2102ff2e610de594aae556d8cb677536d2f873e5a8f8@group.calendar.google.com; \
	python main.py

deploy:
	gcloud functions deploy aikatsu_calendar_update \
		--runtime python310 \
		--trigger-http \
		--entry-point main \
		--set-env-vars CALENDAR_ID=43363a9f06275a2a761d2102ff2e610de594aae556d8cb677536d2f873e5a8f8@group.calendar.google.com \
		--allow-unauthenticated

schedule:
	gcloud scheduler jobs update http aikatsu-schedule-job \
		--schedule "0 0 * * *" \
		--time-zone "Asia/Tokyo" \
		--http-method GET \
		--uri "https://us-central1-academycalendar-460009.cloudfunctions.net/aikatsu_calendar_update" \
		--location "us-central1"
