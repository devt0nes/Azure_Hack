import React, { useEffect, useState } from 'react';
import axios from 'axios';
import useAuthStore from '../store/authStore';

const Profile: React.FC = () => {
  const [profile, setProfile] = useState<any>(null);
  const authToken = useAuthStore((state) => state.authToken);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const response = await axios.get('http://localhost:5000/api/profile', {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        setProfile(response.data);
      } catch (error) {
        console.error('Failed to fetch profile:', error);
        alert('Failed to fetch profile. Please try again.');
      }
    };

    fetchProfile();
  }, [authToken]);

  return (
    <div>
      <h1>Profile</h1>
      {profile ? (
        <div>
          <p>Email: {profile.email}</p>
        </div>
      ) : (
        <p>Loading...</p>
      )}
    </div>
  );
};

export default Profile;